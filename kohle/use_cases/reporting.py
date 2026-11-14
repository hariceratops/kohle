"""Reports that read prices. Kept out of `journal.py` because the guard in
tests/test_price_guards.py forbids recording modules from touching prices,
and out of `prices.py` so report code never shares a module with the price
writers (design §2.1)."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import assert_never, overload

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    HistoryError,
    PositionsError,
    PriceError,
    ValuationError,
)
from kohle.domain.models import UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.account_services import get_account_by_name_service
from kohle.services.price_services import price_bindings_service
from kohle.services.state_services import list_state_entries_service
from kohle.services.unit_services import get_unit_by_identifier_service
from kohle.use_cases.bundesland import state_lookup
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


def _market_value(
    quantity: Decimal, close: LatestClose | None, at_cost: Decimal, rate: LatestClose | None = None
) -> Decimal:
    """One valuation rule for both cost bases: the caller says what a row with
    no close falls back to. A close quoted in another currency is converted by
    `rate`; a missing rate falls back like a missing close."""
    match close:
        case Fresh(c) | Stale(c):
            match rate:
                case None:
                    return quantity * c.price
                case Fresh(r) | Stale(r):
                    return quantity * c.price * r.price
                case NoClose():
                    return at_cost
                case _:
                    assert_never(rate)
        case NoClose():
            return at_cost
        case None:
            return quantity
        case _:
            assert_never(close)


@overload
def valuation_status(close: LatestClose, rate: LatestClose | None) -> LatestClose: ...
@overload
def valuation_status(close: LatestClose | None, rate: LatestClose | None) -> LatestClose | None: ...
def valuation_status(close: LatestClose | None, rate: LatestClose | None) -> LatestClose | None:
    """The worse of the close and its rate; a stale result carries the older date."""
    if rate is None:
        return close
    if isinstance(close, NoClose) or isinstance(rate, NoClose):
        return NoClose()
    if isinstance(close, Stale) or isinstance(rate, Stale):
        stale = [x.close for x in (close, rate) if isinstance(x, Stale)]
        return Stale(min(stale, key=lambda p: p.price_date))
    return close


def _quote(
    ctx: DbTransactionContext,
    unit_id: int,
    as_of: date,
    max_age_days: int,
    rates: dict[str, LatestClose],
) -> Result[tuple[LatestClose, LatestClose | None], PriceError]:
    """A unit's latest close and, when that close is quoted in a non-base
    currency, the latest rate of that currency. `rates` holds the rates already
    read by one report, so every row of it uses the same rate."""
    close_res = latest_close(ctx, unit_id, as_of, max_age_days)
    if close_res.is_err:
        return Result.err(close_res.unwrap_err())
    close = close_res.unwrap()
    if isinstance(close, NoClose) or close.close.currency == BASE_CURRENCY:
        return Result.ok((close, None))
    code = close.close.currency
    if code not in rates:
        unit_res = get_unit_by_identifier_service(ctx, code)
        if unit_res.is_err:
            return Result.err(PriceError(str(unit_res.unwrap_err())))
        rate_res = latest_close(ctx, unit_res.unwrap().id, as_of, max_age_days)
        if rate_res.is_err:
            return Result.err(rate_res.unwrap_err())
        rates[code] = rate_res.unwrap()
    return Result.ok((close, rates[code]))


@dataclass(frozen=True, slots=True)
class ValuedBalance:
    balance: UnitBalance
    close: LatestClose | None  # None: no close was looked up (base currency or zero quantity)
    rate: LatestClose | None = None  # the close's currency in euros, when the close is not in euros

    @property
    def status(self) -> LatestClose | None:
        return valuation_status(self.close, self.rate)

    @property
    def market_value(self) -> Decimal:
        return _market_value(self.balance.quantity, self.close, self.balance.at_cost, self.rate)


@dataclass(frozen=True, slots=True)
class Position:
    holding: FifoHolding
    close: LatestClose  # never None: a positions row is always nonzero and non-base
    rate: LatestClose | None = None

    @property
    def status(self) -> LatestClose:
        return valuation_status(self.close, self.rate)

    @property
    def market_value(self) -> Decimal:
        return _market_value(self.holding.quantity, self.close, self.holding.fifo_cost, self.rate)

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
    rates: dict[str, LatestClose] = {}
    for b in balances:
        if b.quantity == 0 or b.unit_identifier == BASE_CURRENCY:
            valued.append(ValuedBalance(b, None))
            continue
        quote_res = _quote(ctx, b.unit_id, as_of, max_age_days, rates)
        if quote_res.is_err:
            return Result.err(quote_res.unwrap_err())
        close, rate = quote_res.unwrap()
        valued.append(ValuedBalance(b, close, rate))
    return Result.ok(valued)


def at_market(rows: Iterable[ValuedRow]) -> Decimal:
    return sum((r.market_value for r in rows), Decimal(0))


def fifo_cost(positions: Iterable[Position]) -> Decimal:
    return sum((p.holding.fifo_cost for p in positions), Decimal(0))


def unrealised_gain(positions: Iterable[Position]) -> Decimal:
    return sum((p.unrealised_gain for p in positions), Decimal(0))


def _row_unit(row: ValuedRow) -> tuple[int, str, Decimal]:
    if isinstance(row, Position):
        return row.holding.unit_id, row.holding.unit_identifier, row.holding.quantity
    return row.balance.unit_id, row.balance.unit_identifier, row.balance.quantity


def row_kind(row: ValuedRow) -> UnitKind | None:
    return row.holding.kind if isinstance(row, Position) else row.balance.kind


def holding_currencies(
    ctx: DbTransactionContext, rows: Iterable[ValuedRow]
) -> Result[dict[int, str], PriceError]:
    """The currency each row's unit is held in: a currency unit is itself, a
    bound security is its binding's quote currency, anything else is euros."""
    rows = list(rows)
    securities = [_row_unit(r)[0] for r in rows if row_kind(r) is not UnitKind.currency]
    bindings_res = price_bindings_service(ctx, securities)
    if bindings_res.is_err:
        return Result.err(bindings_res.unwrap_err())
    quote = {b.unit_id: b.quote_currency for b in bindings_res.unwrap()}
    currencies = {
        unit_id: identifier if row_kind(r) is UnitKind.currency else quote.get(unit_id, BASE_CURRENCY)
        for r in rows
        for unit_id, identifier, _ in [_row_unit(r)]
    }
    return Result.ok(currencies)


@dataclass(frozen=True, slots=True)
class Subtotal:
    currency: str
    native: Decimal | None  # None: some member has no close in this currency
    euro: Decimal


def _native_value(row: ValuedRow, currency: str) -> Decimal | None:
    _, identifier, quantity = _row_unit(row)
    if identifier == currency and row_kind(row) is UnitKind.currency:
        return quantity
    if quantity == 0:
        return Decimal(0)
    match row.close:
        case Fresh(c) | Stale(c) if c.currency == currency:
            return quantity * c.price
        case _:
            return None


def subtotals(rows: Iterable[ValuedRow], currencies: Mapping[int, str]) -> list[Subtotal]:
    """One subtotal per currency, euros first; empty when everything is in euros
    so that a euro-only ledger prints nothing new."""
    grouped: dict[str, list[ValuedRow]] = {}
    for r in rows:
        grouped.setdefault(currencies[_row_unit(r)[0]], []).append(r)
    if grouped.keys() <= {BASE_CURRENCY}:
        return []
    result: list[Subtotal] = []
    for code in sorted(grouped, key=lambda c: (c != BASE_CURRENCY, c)):
        members = grouped[code]
        natives = [_native_value(r, code) for r in members]
        native = None if any(n is None for n in natives) else sum((n for n in natives if n is not None), Decimal(0))
        result.append(Subtotal(code, native, at_market(members)))
    return result


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
        status = r.status
        if status is None:
            continue
        holdings += 1
        if isinstance(status, Stale):
            stale += 1
        elif isinstance(status, NoClose):
            no_price += 1
    return EstimateSummary(holdings, stale, no_price)


@dataclass(frozen=True, slots=True)
class ValuedNetWorthReport:
    at_cost: NetWorthReport
    own: list[ValuedBalance]
    receivables: list[ValuedBalance]
    subtotals: list[Subtotal] = field(default_factory=list)

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
            valued = valued_res.unwrap()
            rows = [*valued.own, *valued.receivables]
            currencies_res = holding_currencies(ctx, rows)
            if currencies_res.is_err:
                return Result.err(currencies_res.unwrap_err())
            return Result.ok(
                replace(valued, subtotals=subtotals(rows, currencies_res.unwrap()))
            )

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


@dataclass(frozen=True, slots=True)
class PositionsReport:
    positions: list[Position]
    subtotals: list[Subtotal]


class QueryPositions(UnitOfWork[PositionsReport, PositionsError]):
    """Held securities at their latest close beside FIFO cost. The replay and
    every close read share one transaction."""

    def execute(self, today: date, max_age_days: int) -> Result[PositionsReport, PositionsError]:
        def use_case(ctx: DbTransactionContext) -> Result[PositionsReport, PositionsError]:
            replay_res = replay_ledger(ctx)
            if replay_res.is_err:
                return Result.err(replay_res.unwrap_err())

            positions: list[Position] = []
            rates: dict[str, LatestClose] = {}
            for holding in replay_res.unwrap().holdings:
                quote_res = _quote(ctx, holding.unit_id, today, max_age_days, rates)
                if quote_res.is_err:
                    return Result.err(quote_res.unwrap_err())
                close, rate = quote_res.unwrap()
                positions.append(Position(holding, close, rate))
            currencies_res = holding_currencies(ctx, positions)
            if currencies_res.is_err:
                return Result.err(currencies_res.unwrap_err())
            return Result.ok(PositionsReport(positions, subtotals(positions, currencies_res.unwrap())))

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
        role: Role | None = None,
    ) -> Result[list[HistoryRow], HistoryError]:
        def use_case(ctx: DbTransactionContext) -> Result[list[HistoryRow], HistoryError]:
            rules_res = current_sampling_rules(ctx)
            if rules_res.is_err:
                return Result.err(rules_res.unwrap_err())

            entries_res = list_state_entries_service(ctx)
            if entries_res.is_err:
                return Result.err(entries_res.unwrap_err())
            lookup_res = state_lookup(entries_res.unwrap())
            if lookup_res.is_err:
                return Result.err(lookup_res.unwrap_err())

            lines_res = net_worth_lines(ctx)
            if lines_res.is_err:
                return Result.err(lines_res.unwrap_err())
            lines = lines_res.unwrap()

            if start is None:
                first = min((ln.entry.entry_date for ln in lines.own + lines.receivables), default=end)
                first_day = min(first, end)
            else:
                first_day = start
            samples = sample_dates(rules_res.unwrap(), lookup_res.unwrap(), first_day, end)
            if role is not None:
                # Filtering before the fold and valuation is safe: the fold is over a prefix.
                samples = [s for s in samples if role in s.roles or s.on == end]
            dates = [s.on for s in samples]

            own = aggregate_by_unit_through(lines.own, dates, lines.costs)
            receivables = aggregate_by_unit_through(lines.receivables, dates, lines.costs)

            rows: list[HistoryRow] = []
            for sample, o, r in zip(samples, own, receivables, strict=True):
                valued_res = valued_net_worth(ctx, NetWorthReport(o, r), sample.on, max_age_days)
                if valued_res.is_err:
                    return Result.err(valued_res.unwrap_err())
                rows.append(HistoryRow(sample.on, sample.roles, valued_res.unwrap()))
            return Result.ok(rows)

        return self._run(use_case)
