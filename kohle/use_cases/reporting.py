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
from kohle.domain.domain_errors import (
    HistoryError,
    PositionsError,
    PriceError,
    ValuationError,
)
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.account_services import get_account_by_name_service
from kohle.use_cases.journal import (
    BASE_CURRENCY,
    NetWorthReport,
    UnitBalance,
    account_balance,
    aggregate_by_unit_through,
    net_worth,
    net_worth_lines,
)
from kohle.use_cases.lots import FifoHolding, replay_ledger
from kohle.use_cases.prices import Fresh, LatestClose, NoClose, Stale, latest_close
from kohle.use_cases.sampling import Role, current_sampling_rules, sample_dates


def _market_value(quantity: Decimal, close: LatestClose | None, at_cost: Decimal) -> Decimal:
    """One valuation rule for both cost bases: the caller says what a row with
    no close falls back to."""
    match close:
        case Fresh(c) | Stale(c):
            return quantity * c.price
        case NoClose():
            return at_cost
        case None:
            return quantity
        case _:
            assert_never(close)


@dataclass(frozen=True, slots=True)
class ValuedBalance:
    balance: UnitBalance
    close: LatestClose | None  # None: no close was looked up (base currency or zero quantity)

    @property
    def market_value(self) -> Decimal:
        return _market_value(self.balance.quantity, self.close, self.balance.at_cost)


@dataclass(frozen=True, slots=True)
class Position:
    holding: FifoHolding
    close: LatestClose  # never None: a positions row is always nonzero and non-base

    @property
    def market_value(self) -> Decimal:
        return _market_value(self.holding.quantity, self.close, self.holding.fifo_cost)

    @property
    def unrealised_gain(self) -> Decimal:
        return self.market_value - self.holding.fifo_cost


ValuedRow = ValuedBalance | Position


def value_balances(
    ctx: DbTransactionContext,
    balances: Iterable[UnitBalance],
    as_of: date,
    max_age_days: int,
) -> Result[list[ValuedBalance], PriceError]:
    """The only place a close is read, and the only place the lookup
    condition is written."""
    valued: list[ValuedBalance] = []
    for b in balances:
        if b.quantity == 0 or b.unit_identifier == BASE_CURRENCY:
            valued.append(ValuedBalance(b, None))
            continue
        close_res = latest_close(ctx, b.unit_id, as_of, max_age_days)
        if close_res.is_err:
            return Result.err(close_res.unwrap_err())
        valued.append(ValuedBalance(b, close_res.unwrap()))
    return Result.ok(valued)


def at_market(rows: Iterable[ValuedRow]) -> Decimal:
    return sum((r.market_value for r in rows), Decimal(0))


def fifo_cost(positions: Iterable[Position]) -> Decimal:
    return sum((p.holding.fifo_cost for p in positions), Decimal(0))


def unrealised_gain(positions: Iterable[Position]) -> Decimal:
    return sum((p.unrealised_gain for p in positions), Decimal(0))


@dataclass(frozen=True, slots=True)
class EstimateSummary:
    holdings: int
    stale: int
    no_price: int

    @property
    def estimated(self) -> int:
        return self.stale + self.no_price


def summarise(rows: Iterable[ValuedRow]) -> EstimateSummary:
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


def valued_net_worth(
    ctx: DbTransactionContext, report: NetWorthReport, as_of: date, max_age_days: int
) -> Result[ValuedNetWorthReport, PriceError]:
    """Values a net-worth fold as of a date. Shared by `ValuedNetWorth` and
    each date of the history, so the two cannot drift apart."""
    own_res = value_balances(ctx, report.own, as_of, max_age_days)
    if own_res.is_err:
        return Result.err(own_res.unwrap_err())

    receivables_res = value_balances(ctx, report.receivables, as_of, max_age_days)
    if receivables_res.is_err:
        return Result.err(receivables_res.unwrap_err())

    return Result.ok(ValuedNetWorthReport(report, own_res.unwrap(), receivables_res.unwrap()))


class ValuedNetWorth(UnitOfWork[ValuedNetWorthReport, ValuationError]):
    """Net worth with each holding at its latest close beside the at-cost
    figure. The fold and every close read share one transaction."""

    def execute(self, today: date, max_age_days: int) -> Result[ValuedNetWorthReport, ValuationError]:
        def use_case(ctx: DbTransactionContext) -> Result[ValuedNetWorthReport, ValuationError]:
            report_res = net_worth(ctx)
            if report_res.is_err:
                return Result.err(report_res.unwrap_err())
            valued_res = valued_net_worth(ctx, report_res.unwrap(), today, max_age_days)
            if valued_res.is_err:
                return Result.err(valued_res.unwrap_err())
            return Result.ok(valued_res.unwrap())

        return self._run(use_case)


class QueryValuedBalance(UnitOfWork[list[ValuedBalance], ValuationError]):
    """An account subtree's balances at their latest close. The fold and every
    close read share one transaction."""

    def execute(
        self, account_name: str, today: date, max_age_days: int
    ) -> Result[list[ValuedBalance], ValuationError]:
        def use_case(ctx: DbTransactionContext) -> Result[list[ValuedBalance], ValuationError]:
            account_res = get_account_by_name_service(ctx, account_name)
            if account_res.is_err:
                return Result.err(account_res.unwrap_err())

            balances_res = account_balance(ctx, account_res.unwrap().id)
            if balances_res.is_err:
                return Result.err(balances_res.unwrap_err())

            valued_res = value_balances(ctx, balances_res.unwrap(), today, max_age_days)
            if valued_res.is_err:
                return Result.err(valued_res.unwrap_err())

            return Result.ok(valued_res.unwrap())

        return self._run(use_case)


class QueryPositions(UnitOfWork[list[Position], PositionsError]):
    """Held securities at their latest close beside FIFO cost. The replay and
    every close read share one transaction."""

    def execute(self, today: date, max_age_days: int) -> Result[list[Position], PositionsError]:
        def use_case(ctx: DbTransactionContext) -> Result[list[Position], PositionsError]:
            replay_res = replay_ledger(ctx)
            if replay_res.is_err:
                return Result.err(replay_res.unwrap_err())

            positions: list[Position] = []
            for holding in replay_res.unwrap().holdings:
                close_res = latest_close(ctx, holding.unit_id, today, max_age_days)
                if close_res.is_err:
                    return Result.err(close_res.unwrap_err())
                positions.append(Position(holding, close_res.unwrap()))
            return Result.ok(positions)

        return self._run(use_case)


@dataclass(frozen=True, slots=True)
class HistoryRow:
    on: date
    roles: tuple[Role, ...]
    report: ValuedNetWorthReport


class NetWorthHistory(UnitOfWork[list[HistoryRow], HistoryError]):
    """Net worth at each sample date, valued by `valued_net_worth`'s rule as
    of that date. The lines load once, the fold runs once, and every close
    read shares the transaction."""

    def execute(
        self,
        start: date | None,
        end: date,
        max_age_days: int,
        state: str,
        role: Role | None = None,
    ) -> Result[list[HistoryRow], HistoryError]:
        def use_case(ctx: DbTransactionContext) -> Result[list[HistoryRow], HistoryError]:
            rules_res = current_sampling_rules(ctx)
            if rules_res.is_err:
                return Result.err(rules_res.unwrap_err())

            lines_res = net_worth_lines(ctx)
            if lines_res.is_err:
                return Result.err(lines_res.unwrap_err())
            lines = lines_res.unwrap()

            if start is None:
                first = min((ln.entry.entry_date for ln in lines.own + lines.receivables), default=end)
                first_day = min(first, end)
            else:
                first_day = start
            samples = sample_dates(rules_res.unwrap(), lambda _: state, first_day, end)
            if role is not None:
                # Filtering before the fold and valuation is safe: the fold is over a prefix.
                samples = [s for s in samples if role in s.roles or s.on == end]
            dates = [s.on for s in samples]

            own = aggregate_by_unit_through(lines.own, dates)
            receivables = aggregate_by_unit_through(lines.receivables, dates)

            rows: list[HistoryRow] = []
            for sample, o, r in zip(samples, own, receivables, strict=True):
                valued_res = valued_net_worth(ctx, NetWorthReport(o, r), sample.on, max_age_days)
                if valued_res.is_err:
                    return Result.err(valued_res.unwrap_err())
                rows.append(HistoryRow(sample.on, sample.roles, valued_res.unwrap()))
            return Result.ok(rows)

        return self._run(use_case)
