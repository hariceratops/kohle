"""FIFO lot replay: realised gain from the ledger alone (spec: portfolio-and-profit-reporting).

Price-free on purpose: a test forbids this module from referencing prices, so
gain depends only on recorded unit prices, never on a fetched close. Lots are
rebuilt from the ledger on every run and never stored.
"""

import bisect
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from fractions import Fraction

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    BalanceError,
    CurrencyWithPeople,
    LotError,
    LotShortfall,
    RealisedError,
    SecurityMoveWithPeople,
    UnbalancedOwnMove,
)
from kohle.domain.models import BASE_CURRENCY, JournalLine, Unit, UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.journal_services import (
    account_lines_service,
    currency_lines_service,
)
from kohle.use_cases.accounts import balance_sheet_accounts


@dataclass(frozen=True, slots=True)
class Lot:
    acquired: date
    line_id: int
    quantity: Decimal
    unit_cost: Fraction

    @property
    def cost(self) -> Fraction:
        return Fraction(self.quantity) * self.unit_cost


def _decimal(value: Fraction) -> Decimal:
    return Decimal(value.numerator) / Decimal(value.denominator)


@dataclass(frozen=True, slots=True)
class Sale:
    entry_date: date
    account_name: str
    unit_identifier: str
    quantity: Decimal
    proceeds: Decimal
    fifo_cost: Decimal

    @property
    def gain(self) -> Decimal:
        return self.proceeds - self.fifo_cost


@dataclass(frozen=True, slots=True)
class FifoHolding:
    unit_identifier: str
    unit_id: int
    quantity: Decimal
    fifo_cost: Decimal
    kind: UnitKind | None = None


@dataclass(frozen=True, slots=True)
class LotReplay:
    sales: list[Sale]
    holdings: list[FifoHolding]
    # Euro value by line id, for the lines whose value comes from currency lots:
    # every line of a foreign currency and every line priced in one.
    costs: dict[int, Decimal] = field(default_factory=dict)


def _replayed(unit: Unit) -> bool:
    """With `_foreign_currency`, the only place the feature names a kind. The
    base currency is cash, not a lot."""
    return unit.kind is UnitKind.security or _foreign_currency(unit)


def _foreign_currency(unit: Unit) -> bool:
    return unit.kind is UnitKind.currency and unit.identifier != BASE_CURRENCY


def _lot_valued(line: JournalLine) -> bool:
    return _foreign_currency(line.unit) or line.price_unit_id is not None


def _acquisition(lot: Lot) -> tuple[date, int]:
    return lot.acquired, lot.line_id


def _take(queue: list[Lot], quantity: Decimal) -> tuple[list[Lot], Decimal]:
    """Remove up to `quantity` from the front of `queue`; returns the lots
    taken (the last possibly split off) and the shortfall."""
    taken: list[Lot] = []
    remaining = quantity
    while remaining > 0 and queue:
        front = queue[0]
        if front.quantity <= remaining:
            taken.append(queue.pop(0))
            remaining -= front.quantity
        else:
            taken.append(Lot(front.acquired, front.line_id, remaining, front.unit_cost))
            queue[0] = Lot(front.acquired, front.line_id, front.quantity - remaining, front.unit_cost)
            remaining = Decimal(0)
    return taken, remaining


def _sale(line: JournalLine, account_name: str, taken: list[Lot]) -> Sale:
    return Sale(
        entry_date=line.entry.entry_date,
        account_name=account_name,
        unit_identifier=line.unit.identifier,
        quantity=line.quantity,
        proceeds=line.value,
        fifo_cost=_decimal(sum((lot.cost for lot in taken), Fraction(0))),
    )


def _move(
    queues: dict[tuple[int, str], list[Lot]],
    own: dict[int, str],
    credits: list[JournalLine],
    debits: list[JournalLine],
    costs: dict[int, Fraction] | None,
) -> LotError | None:
    """Lots keep their dates and costs; the move lines' own prices are ignored.
    `costs` collects what each line carried when the caller wants it."""
    first = credits[0]
    moved_out = sum((line.quantity for line in credits), Decimal(0))
    moved_in = sum((line.quantity for line in debits), Decimal(0))
    if moved_out != moved_in:
        return UnbalancedOwnMove(first.entry.id, first.entry.entry_date, first.unit.identifier, moved_out, moved_in)

    pool: list[Lot] = []
    for line in credits:
        queue = queues.setdefault((line.account_id, line.unit.identifier), [])
        taken, shortfall = _take(queue, line.quantity)
        if shortfall > 0:
            return LotShortfall(line.unit.identifier, own[line.account_id], line.entry.entry_date, shortfall)
        if costs is not None:
            costs[line.id] = sum((lot.cost for lot in taken), Fraction(0))
        pool.extend(taken)
    pool.sort(key=_acquisition)

    for line in debits:
        queue = queues.setdefault((line.account_id, line.unit.identifier), [])
        dealt, _ = _take(pool, line.quantity)
        if costs is not None:
            costs[line.id] = sum((lot.cost for lot in dealt), Fraction(0))
        for lot in dealt:
            bisect.insort(queue, lot, key=_acquisition)
    return None


@dataclass(slots=True)
class _Book:
    """What one replay accumulates; local to a call."""

    own: dict[int, str]
    people: dict[int, str]
    queues: dict[tuple[int, str], list[Lot]] = field(default_factory=dict)
    unit_ids: dict[str, int] = field(default_factory=dict)
    unit_kinds: dict[str, UnitKind] = field(default_factory=dict)
    sales: list[Sale] = field(default_factory=list)
    costs: dict[int, Fraction] = field(default_factory=dict)


def _process_unit(book: _Book, unit_lines: list[JournalLine], paid: dict[int, tuple[Fraction, Decimal]]) -> LotError | None:
    """One unit's lines of one entry. `paid` collects, per currency unit id, the
    cost and quantity its at-par credits used up, for `_apportion`."""
    first = unit_lines[0]
    identifier = first.unit.identifier
    currency = _foreign_currency(first.unit)
    group = [line for line in unit_lines if line.account_id in book.own]
    person_line = next((line for line in unit_lines if line.account_id in book.people), None)
    if person_line is not None and group:
        return SecurityMoveWithPeople(
            person_line.entry.id,
            person_line.entry.entry_date,
            identifier,
            book.own[group[0].account_id],
            book.people[person_line.account_id],
        )
    if currency:
        for line in unit_lines:
            if line.account_id not in book.own and line.account_id not in book.people and line.price_unit_id is None:
                book.costs[line.id] = Fraction(line.value)
    if not group:
        return None

    book.unit_ids.setdefault(identifier, first.unit_id)
    book.unit_kinds.setdefault(identifier, first.unit.kind)
    credits = [line for line in group if not line.is_debit]
    debits = [line for line in group if line.is_debit]

    if credits and debits:
        return _move(book.queues, book.own, credits, debits, book.costs if currency else None)

    for line in debits:
        queue = book.queues.setdefault((line.account_id, identifier), [])
        # A stated total is exact where a per-unit price rounded to the column is not.
        value = book.costs.get(line.id, Fraction(line.value))
        if currency:
            book.costs[line.id] = value
        bisect.insort(queue, Lot(line.entry.entry_date, line.id, line.quantity, value / Fraction(line.quantity)), key=_acquisition)
    for line in credits:
        queue = book.queues.setdefault((line.account_id, identifier), [])
        taken, shortfall = _take(queue, line.quantity)
        if shortfall > 0:
            return LotShortfall(identifier, book.own[line.account_id], line.entry.entry_date, shortfall)
        if currency:
            consumed = sum((lot.cost for lot in taken), Fraction(0))
            book.costs[line.id] = consumed
            if line.price_unit_id is not None:
                cost, quantity = paid.get(line.unit_id, (Fraction(0), Decimal(0)))
                paid[line.unit_id] = (cost + consumed, quantity + line.quantity)
                continue
        book.sales.append(_sale(line, book.own[line.account_id], taken))
    return None


def _currency_with_people(book: _Book, entry_lines: list[JournalLine]) -> CurrencyWithPeople | None:
    """Currencies are held in lots, which People accounts do not have; the
    who-owes-what fold would otherwise read such a line as euros."""
    for line in entry_lines:
        if line.account_id in book.people and _lot_valued(line):
            unit = line.unit if _foreign_currency(line.unit) else line.price_unit
            return CurrencyWithPeople(line.entry.id, line.entry.entry_date, unit.identifier, book.people[line.account_id])
    return None


def _apportion(book: _Book, entry_lines: list[JournalLine], paid: dict[int, tuple[Fraction, Decimal]]) -> None:
    """The cost a payment consumed goes to the lines priced in that currency, in
    proportion to their value in it. The divisor is the quantity paid, not the
    sum of the lines loaded: by the entry's balance they are equal, and a
    partial load then still gives each line its own share."""
    for unit_id, (cost, quantity) in paid.items():
        for line in entry_lines:
            paying = line.unit_id == unit_id and (line.account_id in book.own or line.account_id in book.people)
            if line.price_unit_id == unit_id and not paying:
                book.costs[line.id] = cost * Fraction(line.value) / Fraction(quantity)


def replay(
    lines: Iterable[JournalLine],
    own: dict[int, str],
    people: dict[int, str] | None = None,
    lots_for: Callable[[Unit], bool] = lambda unit: True,
) -> Result[LotReplay, LotError]:
    """`lines` must be in `(entry_date, line id)` order. `lots_for` decides which
    units get lots, and by default every unit does, since a unit with no kind
    is replayed as a security. The ledger report passes `_replayed`; the fold's
    readers pass `_foreign_currency`, so that a security shortfall cannot fail
    `net-worth`.

    An entry is replayed as a whole, because what a purchase paid in a currency
    costs is what that currency's lots cost: currencies first, then the lines
    they paid for, then every other unit."""
    book = _Book(own, people or {})
    entries: dict[int, list[JournalLine]] = {}
    for line in lines:
        entries.setdefault(line.entry.id, []).append(line)

    for entry_lines in entries.values():
        refusal = _currency_with_people(book, entry_lines)
        if refusal is not None:
            return Result.err(refusal)
        by_unit: dict[str, list[JournalLine]] = {}
        for line in entry_lines:
            by_unit.setdefault(line.unit.identifier, []).append(line)
        replayed = [unit_lines for unit_lines in by_unit.values() if lots_for(unit_lines[0].unit)]
        currencies = [unit_lines for unit_lines in replayed if _foreign_currency(unit_lines[0].unit)]
        others = [unit_lines for unit_lines in replayed if not _foreign_currency(unit_lines[0].unit)]

        paid: dict[int, tuple[Fraction, Decimal]] = {}
        for unit_lines in currencies:
            error = _process_unit(book, unit_lines, paid)
            if error is not None:
                return Result.err(error)
        _apportion(book, entry_lines, paid)
        for unit_lines in others:
            error = _process_unit(book, unit_lines, paid)
            if error is not None:
                return Result.err(error)

    holdings: list[FifoHolding] = []
    for identifier, unit_id in book.unit_ids.items():
        held = [lot for (_, ident), queue in book.queues.items() if ident == identifier for lot in queue]
        quantity = sum((lot.quantity for lot in held), Decimal(0))
        if quantity != 0:
            holdings.append(
                FifoHolding(
                    identifier,
                    unit_id,
                    quantity,
                    _decimal(sum((lot.cost for lot in held), Fraction(0))),
                    book.unit_kinds[identifier],
                )
            )
    return Result.ok(LotReplay(book.sales, holdings, {line_id: _decimal(cost) for line_id, cost in book.costs.items()}))


def replay_ledger(ctx: DbTransactionContext) -> Result[LotReplay, RealisedError]:
    accounts_res = balance_sheet_accounts(ctx)
    if accounts_res.is_err:
        return Result.err(accounts_res.unwrap_err())
    accounts = accounts_res.unwrap()

    lines_res = account_lines_service(ctx, accounts.own.keys() | accounts.people.keys())
    if lines_res.is_err:
        return Result.err(lines_res.unwrap_err())

    replay_res = replay(lines_res.unwrap(), accounts.own, accounts.people, lots_for=_replayed)
    if replay_res.is_err:
        return Result.err(replay_res.unwrap_err())
    return Result.ok(replay_res.unwrap())


def line_costs(ctx: DbTransactionContext, lines: Iterable[JournalLine]) -> Result[dict[int, Decimal], BalanceError]:
    """The euro value of every line whose value comes from a currency's lots, by
    line id, for a fold that must read what the replay reads. `{}` at once when
    none of `lines` is such a line, so a ledger with no foreign currency runs no
    replay and no extra query."""
    if not any(_lot_valued(line) for line in lines):
        return Result.ok({})

    accounts_res = balance_sheet_accounts(ctx)
    if accounts_res.is_err:
        return Result.err(accounts_res.unwrap_err())
    accounts = accounts_res.unwrap()

    loaded_res = currency_lines_service(ctx, BASE_CURRENCY)
    if loaded_res.is_err:
        return Result.err(loaded_res.unwrap_err())

    replay_res = replay(loaded_res.unwrap(), accounts.own, accounts.people, lots_for=_foreign_currency)
    if replay_res.is_err:
        return Result.err(replay_res.unwrap_err())
    return Result.ok(replay_res.unwrap().costs)


def realised_gain(sales: Iterable[Sale]) -> Decimal:
    return sum((sale.gain for sale in sales), Decimal(0))


class QueryRealised(UnitOfWork[list[Sale], RealisedError]):
    def execute(self, year: int | None) -> Result[list[Sale], RealisedError]:
        def use_case(ctx: DbTransactionContext) -> Result[list[Sale], RealisedError]:
            replay_res = replay_ledger(ctx)
            if replay_res.is_err:
                return Result.err(replay_res.unwrap_err())
            sales = replay_res.unwrap().sales
            if year is not None:
                sales = [sale for sale in sales if sale.entry_date.year == year]
            return Result.ok(sales)

        return self._run(use_case)
