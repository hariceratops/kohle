"""FIFO lot replay: realised gain from the ledger alone (spec: portfolio-and-profit-reporting).

Price-free on purpose: a test forbids this module from referencing prices, so
gain depends only on recorded unit prices, never on a fetched close. Lots are
rebuilt from the ledger on every run and never stored.
"""

import bisect
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    LotError,
    LotShortfall,
    RealisedError,
    SecurityMoveWithPeople,
    UnbalancedOwnMove,
)
from kohle.domain.models import JournalLine, Unit, UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.journal_services import account_lines_service
from kohle.use_cases.journal import balance_sheet_accounts


@dataclass(frozen=True, slots=True)
class Lot:
    acquired: date
    line_id: int
    quantity: Decimal
    unit_cost: Decimal

    @property
    def cost(self) -> Decimal:
        return self.quantity * self.unit_cost


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


@dataclass(frozen=True, slots=True)
class LotReplay:
    sales: list[Sale]
    holdings: list[FifoHolding]


def _replayed(unit: Unit) -> bool:
    """The one place the feature names a kind. A wider filter must still
    exclude the base currency."""
    return unit.kind is UnitKind.security


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
        proceeds=line.quantity * line.unit_price,
        fifo_cost=sum((lot.cost for lot in taken), Decimal(0)),
    )


def _move(
    queues: dict[tuple[int, str], list[Lot]],
    own: dict[int, str],
    credits: list[JournalLine],
    debits: list[JournalLine],
) -> LotError | None:
    """Lots keep their dates and costs; the move lines' own prices are ignored."""
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
        pool.extend(taken)
    pool.sort(key=_acquisition)

    for line in debits:
        queue = queues.setdefault((line.account_id, line.unit.identifier), [])
        dealt, _ = _take(pool, line.quantity)
        for lot in dealt:
            bisect.insort(queue, lot, key=_acquisition)
    return None


def replay(
    lines: Iterable[JournalLine], own: dict[int, str], people: dict[int, str] | None = None
) -> Result[LotReplay, LotError]:
    """`lines` must be in `(entry_date, line id)` order and already filtered by `_replayed`."""
    people = people or {}
    groups: dict[tuple[int, str], list[JournalLine]] = {}
    for line in lines:
        if line.account_id in own or line.account_id in people:
            groups.setdefault((line.entry.id, line.unit.identifier), []).append(line)

    queues: dict[tuple[int, str], list[Lot]] = {}
    unit_ids: dict[str, int] = {}
    sales: list[Sale] = []

    for entry_lines in groups.values():
        group = [line for line in entry_lines if line.account_id in own]
        person_line = next((line for line in entry_lines if line.account_id in people), None)
        if person_line is not None and group:
            return Result.err(
                SecurityMoveWithPeople(
                    person_line.entry.id,
                    person_line.entry.entry_date,
                    person_line.unit.identifier,
                    own[group[0].account_id],
                    people[person_line.account_id],
                )
            )
        if not group:
            continue
        identifier = group[0].unit.identifier
        unit_ids.setdefault(identifier, group[0].unit_id)
        credits = [line for line in group if not line.is_debit]
        debits = [line for line in group if line.is_debit]

        if credits and debits:
            move_error = _move(queues, own, credits, debits)
            if move_error is not None:
                return Result.err(move_error)
            continue

        for line in debits:
            queue = queues.setdefault((line.account_id, identifier), [])
            bisect.insort(queue, Lot(line.entry.entry_date, line.id, line.quantity, line.unit_price), key=_acquisition)
        for line in credits:
            queue = queues.setdefault((line.account_id, identifier), [])
            taken, shortfall = _take(queue, line.quantity)
            if shortfall > 0:
                return Result.err(LotShortfall(identifier, own[line.account_id], line.entry.entry_date, shortfall))
            sales.append(_sale(line, own[line.account_id], taken))

    holdings: list[FifoHolding] = []
    for identifier, unit_id in unit_ids.items():
        held = [lot for (_, ident), queue in queues.items() if ident == identifier for lot in queue]
        quantity = sum((lot.quantity for lot in held), Decimal(0))
        if quantity != 0:
            holdings.append(FifoHolding(identifier, unit_id, quantity, sum((lot.cost for lot in held), Decimal(0))))
    return Result.ok(LotReplay(sales, holdings))


def replay_ledger(ctx: DbTransactionContext) -> Result[LotReplay, RealisedError]:
    accounts_res = balance_sheet_accounts(ctx)
    if accounts_res.is_err:
        return Result.err(accounts_res.unwrap_err())
    accounts = accounts_res.unwrap()

    lines_res = account_lines_service(ctx, accounts.own.keys() | accounts.people.keys())
    if lines_res.is_err:
        return Result.err(lines_res.unwrap_err())

    replay_res = replay((line for line in lines_res.unwrap() if _replayed(line.unit)), accounts.own, accounts.people)
    if replay_res.is_err:
        return Result.err(replay_res.unwrap_err())
    return Result.ok(replay_res.unwrap())


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
