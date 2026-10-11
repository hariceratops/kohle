"""Reports that read prices. Kept out of `journal.py` because the guard in
tests/test_price_guards.py forbids recording modules from touching prices,
and out of `prices.py` so report code never shares a module with the price
writers (design §2.1)."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import assert_never

from kohle.core.result import Result
from kohle.domain.domain_errors import PriceError, ValuationError
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.use_cases.journal import (
    BASE_CURRENCY,
    NetWorthReport,
    UnitBalance,
    net_worth,
)
from kohle.use_cases.prices import Fresh, LatestClose, NoClose, Stale, latest_close


@dataclass(frozen=True, slots=True)
class ValuedBalance:
    balance: UnitBalance
    close: LatestClose | None  # None: no close was looked up (base currency or zero quantity)

    @property
    def market_value(self) -> Decimal:
        match self.close:
            case Fresh(c) | Stale(c):
                return self.balance.quantity * c.price
            case NoClose():
                return self.balance.at_cost
            case None:
                return self.balance.quantity
            case _:
                assert_never(self.close)


def value_balances(
    ctx: DbTransactionContext,
    balances: Iterable[UnitBalance],
    today: date,
    max_age_days: int,
) -> Result[list[ValuedBalance], PriceError]:
    """The only place a close is read, and the only place the lookup
    condition is written."""
    valued: list[ValuedBalance] = []
    for b in balances:
        if b.quantity == 0 or b.unit_identifier == BASE_CURRENCY:
            valued.append(ValuedBalance(b, None))
            continue
        close_res = latest_close(ctx, b.unit_id, today, max_age_days)
        if close_res.is_err:
            return Result.err(close_res.unwrap_err())
        valued.append(ValuedBalance(b, close_res.unwrap()))
    return Result.ok(valued)


def at_market(rows: Iterable[ValuedBalance]) -> Decimal:
    return sum((r.market_value for r in rows), Decimal(0))


@dataclass(frozen=True, slots=True)
class EstimateSummary:
    holdings: int  # M
    stale: int  # S
    no_price: int  # C

    @property
    def estimated(self) -> int:  # K
        return self.stale + self.no_price


def summarise(rows: Iterable[ValuedBalance]) -> EstimateSummary:
    # `close is not None` is exactly the lookup condition in value_balances,
    # so M is the nonzero non-base rows without a second definition.
    holdings = stale = no_price = 0
    for r in rows:
        if r.close is None:
            continue
        holdings += 1
        if isinstance(r.close, Stale):
            stale += 1
        elif isinstance(r.close, NoClose):
            no_price += 1
    return EstimateSummary(holdings, stale, no_price)


@dataclass(frozen=True, slots=True)
class ValuedNetWorthReport:
    at_cost: NetWorthReport
    own: list[ValuedBalance]
    receivables: list[ValuedBalance]

    @property
    def net_worth_at_market(self) -> Decimal:
        return at_market(self.own) + at_market(self.receivables)

    @property
    def estimates(self) -> EstimateSummary:
        return summarise(self.own + self.receivables)


class ValuedNetWorth(UnitOfWork[ValuedNetWorthReport, ValuationError]):
    """Net worth with each holding at its latest close beside the at-cost
    figure. The fold and every close read share one transaction."""

    def execute(self, today: date, max_age_days: int) -> Result[ValuedNetWorthReport, ValuationError]:
        def use_case(ctx: DbTransactionContext) -> Result[ValuedNetWorthReport, ValuationError]:
            report_res = net_worth(ctx)
            if report_res.is_err:
                return Result.err(report_res.unwrap_err())
            report = report_res.unwrap()

            own_res = value_balances(ctx, report.own, today, max_age_days)
            if own_res.is_err:
                return Result.err(own_res.unwrap_err())

            receivables_res = value_balances(ctx, report.receivables, today, max_age_days)
            if receivables_res.is_err:
                return Result.err(receivables_res.unwrap_err())

            return Result.ok(ValuedNetWorthReport(report, own_res.unwrap(), receivables_res.unwrap()))

        return self._run(use_case)
