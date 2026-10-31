from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session, joinedload

from kohle.core.result import Result
from kohle.domain.domain_errors import CapError
from kohle.domain.models import Account, CapEntry
from kohle.infrastructure.crud import crud_create, crud_retrieve, crud_update
from kohle.infrastructure.transaction_context import DbTransactionContext


@crud_retrieve
def list_cap_entries_service(ctx: DbTransactionContext) -> Result[list[CapEntry], CapError]:
    def op(session: Session) -> list[CapEntry]:
        return (
            session.query(CapEntry)
            # The unit of work closes the session before the caller reads these.
            .options(joinedload(CapEntry.account))
            .join(Account, CapEntry.account_id == Account.id)
            .order_by(Account.name, CapEntry.effective_from)
            .all()
        )

    return ctx.run(op).map_err(lambda err: CapError(str(err)))


@crud_create
def _create_cap_entry_service(
    ctx: DbTransactionContext, account_id: int, effective_from: date, amount: Decimal | None, rule: str | None
) -> Result[CapEntry, CapError]:
    def op(session: Session) -> CapEntry:
        entry = CapEntry(account_id=account_id, effective_from=effective_from, amount=amount, rule=rule)
        session.add(entry)
        return entry

    return ctx.run(op).map_err(lambda err: CapError(str(err)))


@crud_update
def _update_cap_entry_service(
    ctx: DbTransactionContext, entry_id: int, amount: Decimal | None, rule: str | None
) -> Result[CapEntry, CapError]:
    def op(session: Session) -> CapEntry:
        entry = session.get_one(CapEntry, entry_id)
        entry.amount = amount
        entry.rule = rule
        return entry

    return ctx.run(op).map_err(lambda err: CapError(str(err)))


def put_cap_entry_service(
    ctx: DbTransactionContext, account_id: int, effective_from: date, amount: Decimal | None, rule: str | None
) -> Result[CapEntry, CapError]:
    """Create the entry for (account, effective_from), or replace it. The same
    amount and rule write nothing, so a replay leaves no OperationGroup."""
    listed = list_cap_entries_service(ctx)
    if listed.is_err:
        return Result.err(listed.unwrap_err())
    existing = next(
        (e for e in listed.unwrap() if e.account_id == account_id and e.effective_from == effective_from), None
    )
    if existing is None:
        return _create_cap_entry_service(ctx, account_id, effective_from, amount, rule)
    if existing.amount == amount and existing.rule == rule:
        return Result.ok(existing)
    return _update_cap_entry_service(ctx, existing.id, amount, rule)
