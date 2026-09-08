from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session, joinedload

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    DuplicateJournalEntry,
    DuplicateLineInEntry,
    JournalError,
)
from kohle.domain.models import JournalEntry, JournalLine
from kohle.infrastructure.crud import crud_create, crud_retrieve
from kohle.infrastructure.infra_errors import check_if_unique_constraint_failed
from kohle.infrastructure.transaction_context import DbTransactionContext


@dataclass(frozen=True, slots=True)
class LineSpec:
    account_id: int
    unit_id: int
    quantity: Decimal
    unit_price: Decimal
    is_debit: bool

    @property
    def value(self) -> Decimal:
        return self.quantity * self.unit_price


@crud_create
def add_journal_entry_service(
    ctx: DbTransactionContext,
    entry_date: date,
    reference: str,
    description: str,
    lines: Iterable[LineSpec],
) -> Result[JournalEntry, JournalError]:
    def op(session: Session) -> JournalEntry:
        entry = JournalEntry(entry_date=entry_date, reference=reference, description=description)
        entry.lines = [
            JournalLine(
                account_id=line.account_id,
                unit_id=line.unit_id,
                quantity=line.quantity,
                unit_price=line.unit_price,
                is_debit=line.is_debit,
            )
            for line in lines
        ]
        session.add(entry)
        return entry

    return (
        ctx.run(op)
        .map_err(lambda err: (
            DuplicateJournalEntry(reference)
            if check_if_unique_constraint_failed(err, "journal_entries.reference")
            else DuplicateLineInEntry()
            if check_if_unique_constraint_failed(
                err,
                "journal_lines.entry_id, journal_lines.account_id, "
                "journal_lines.unit_id, journal_lines.is_debit",
            )
            else JournalError(str(err))
        ))
    )


@crud_retrieve
def existing_references_service(
    ctx: DbTransactionContext, references: Iterable[str]
) -> Result[set[str], JournalError]:
    def op(session: Session) -> set[str]:
        rows = (
            session.query(JournalEntry.reference)
            .filter(JournalEntry.reference.in_(list(references)))
            .all()
        )
        return {row[0] for row in rows}

    return ctx.run(op).map_err(lambda err: JournalError(str(err)))


@crud_retrieve
def query_lines_by_period_service(
    ctx: DbTransactionContext, account_id: int, start_date: date, end_date: date
) -> Result[list[JournalLine], JournalError]:
    def op(session: Session) -> list[JournalLine]:
        return (
            session.query(JournalLine)
            # The unit of work closes the session before the caller sees these,
            # so anything the caller reads has to be loaded up front.
            .options(joinedload(JournalLine.entry), joinedload(JournalLine.unit))
            .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
            .filter(JournalLine.account_id == account_id)
            .filter(JournalEntry.entry_date.between(start_date, end_date))
            .order_by(JournalEntry.entry_date.asc())
            .all()
        )

    return ctx.run(op).map_err(lambda err: JournalError(str(err)))


@crud_retrieve
def account_lines_service(
    ctx: DbTransactionContext, account_ids: Iterable[int]
) -> Result[list[JournalLine], JournalError]:
    def op(session: Session) -> list[JournalLine]:
        return (
            session.query(JournalLine)
            # The unit of work closes the session before the caller sees these,
            # so anything the caller reads has to be loaded up front.
            .options(joinedload(JournalLine.entry), joinedload(JournalLine.unit))
            .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
            .filter(JournalLine.account_id.in_(list(account_ids)))
            # Load-bearing, not cosmetic: _aggregate_by_unit's moving-average
            # cost fold is order-dependent and consumes this ordering as-is
            # (design §6.4). Changing it silently changes reported averages.
            .order_by(JournalEntry.entry_date.asc(), JournalLine.id.asc())
            .all()
        )

    return ctx.run(op).map_err(lambda err: JournalError(str(err)))
