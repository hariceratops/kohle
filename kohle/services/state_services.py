from datetime import date

from sqlalchemy.orm import Session

from kohle.core.result import Result
from kohle.domain.domain_errors import StateError
from kohle.domain.models import StateEntry
from kohle.infrastructure.crud import crud_create, crud_retrieve, crud_update
from kohle.infrastructure.transaction_context import DbTransactionContext


@crud_retrieve
def list_state_entries_service(ctx: DbTransactionContext) -> Result[list[StateEntry], StateError]:
    def op(session: Session) -> list[StateEntry]:
        return session.query(StateEntry).order_by(StateEntry.effective_from).all()

    return ctx.run(op).map_err(lambda err: StateError(str(err)))


@crud_create
def _create_state_entry_service(
    ctx: DbTransactionContext, effective_from: date, state: str
) -> Result[StateEntry, StateError]:
    def op(session: Session) -> StateEntry:
        entry = StateEntry(effective_from=effective_from, state=state)
        session.add(entry)
        return entry

    return ctx.run(op).map_err(lambda err: StateError(str(err)))


@crud_update
def _update_state_entry_service(
    ctx: DbTransactionContext, entry_id: int, state: str
) -> Result[StateEntry, StateError]:
    def op(session: Session) -> StateEntry:
        entry = session.get_one(StateEntry, entry_id)
        entry.state = state
        return entry

    return ctx.run(op).map_err(lambda err: StateError(str(err)))


def put_state_entry_service(
    ctx: DbTransactionContext, effective_from: date, state: str
) -> Result[StateEntry, StateError]:
    """Create the entry for `effective_from`, or replace its state. The same
    state writes nothing, so a replay leaves no OperationGroup."""
    listed = list_state_entries_service(ctx)
    if listed.is_err:
        return Result.err(listed.unwrap_err())
    existing = next((e for e in listed.unwrap() if e.effective_from == effective_from), None)
    if existing is None:
        return _create_state_entry_service(ctx, effective_from, state)
    if existing.state == state:
        return Result.ok(existing)
    return _update_state_entry_service(ctx, existing.id, state)
