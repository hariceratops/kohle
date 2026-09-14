from sqlalchemy.orm import Session

from kohle.core.result import Result
from kohle.domain.domain_errors import NoSplitForEntry, SplitError
from kohle.domain.models import Split
from kohle.infrastructure.crud import crud_create, crud_retrieve, crud_update
from kohle.infrastructure.transaction_context import DbTransactionContext


@crud_retrieve
def split_by_entry_service(ctx: DbTransactionContext, journal_entry_id: int) -> Result[Split, SplitError]:
    """The one splits row for a journal entry — split-line's and
    reclassify's shared lookup (design §4.4, §5.4)."""

    def op(session: Session) -> Split | None:
        return session.query(Split).filter(Split.journal_entry_id == journal_entry_id).one_or_none()

    return (
        ctx.run(op)
        .map_err(lambda err: SplitError(str(err)))
        .and_then(lambda split:
            Result.ok(split)
            if split is not None
            else Result.err(NoSplitForEntry(journal_entry_id))
        )
    )


@crud_create
def _create_split_service(
    ctx: DbTransactionContext, journal_entry_id: int, adjusting_entry_id: int | None
) -> Result[Split, SplitError]:
    def op(session: Session) -> Split:
        split = Split(journal_entry_id=journal_entry_id, adjusting_entry_id=adjusting_entry_id)
        session.add(split)
        return split

    return ctx.run(op).map_err(lambda err: SplitError(str(err)))


@crud_update
def _update_split_adjusting_entry_service(
    ctx: DbTransactionContext, split_id: int, adjusting_entry_id: int | None
) -> Result[Split, SplitError]:
    def op(session: Session) -> Split | None:
        split = session.get(Split, split_id)
        if split is not None:
            split.adjusting_entry_id = adjusting_entry_id
        return split

    return (
        ctx.run(op)
        .map_err(lambda err: SplitError(str(err)))
        .and_then(lambda split:
            Result.ok(split)
            if split is not None
            else Result.err(SplitError(f"Split id {split_id} not found"))
        )
    )


def set_split_adjusting_entry_service(
    ctx: DbTransactionContext, journal_entry_id: int, adjusting_entry_id: int | None
) -> Result[Split, SplitError]:
    """Insert the splits row for an entry the first time, update it after.

    UniqueConstraint(journal_entry_id) is what makes "the split of this
    line" a phrase with a single referent, so a second split of the same
    entry must be an update rather than a second row (design §4.4).
    """
    existing_res = split_by_entry_service(ctx, journal_entry_id)
    if existing_res.is_ok:
        return _update_split_adjusting_entry_service(ctx, existing_res.unwrap().id, adjusting_entry_id)
    err = existing_res.unwrap_err()
    if isinstance(err, NoSplitForEntry):
        return _create_split_service(ctx, journal_entry_id, adjusting_entry_id)
    return Result.err(err)
