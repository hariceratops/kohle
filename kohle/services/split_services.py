from sqlalchemy.orm import Session, selectinload

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    DuplicateSplitGroup,
    NoSplitForEntry,
    SplitError,
    SplitGroupNotFound,
)
from kohle.domain.models import JournalEntry, JournalLine, Split, SplitGroup
from kohle.infrastructure.crud import crud_create, crud_retrieve, crud_update
from kohle.infrastructure.infra_errors import check_if_unique_constraint_failed
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


@crud_update
def set_split_group_service(
    ctx: DbTransactionContext, journal_entry_id: int, group_id: int | None
) -> Result[Split, SplitError]:
    """`--group` is authoritative on every run of `split-line` (design §5.3):
    absent, it clears the group; given, it sets or moves it. Only called on
    an existing row — `SplitImportedEntry` always posts through
    `set_split_adjusting_entry_service` first, which creates the row on a
    fresh split."""

    def op(session: Session) -> Split | None:
        split = session.query(Split).filter(Split.journal_entry_id == journal_entry_id).one_or_none()
        if split is not None:
            split.group_id = group_id
        return split

    return (
        ctx.run(op)
        .map_err(lambda err: SplitError(str(err)))
        .and_then(lambda split:
            Result.ok(split)
            if split is not None
            else Result.err(SplitError(f"Journal entry id {journal_entry_id} has no split row"))
        )
    )


@crud_create
def add_split_group_service(ctx: DbTransactionContext, name: str) -> Result[SplitGroup, SplitError]:
    def op(session: Session) -> SplitGroup:
        group = SplitGroup(name=name)
        session.add(group)
        return group

    return (
        ctx.run(op)
        .map_err(lambda err: (
            DuplicateSplitGroup(name) if check_if_unique_constraint_failed(err, "split_groups.name")
            else SplitError(str(err))
        ))
    )


@crud_retrieve
def get_split_group_by_name_service(ctx: DbTransactionContext, name: str) -> Result[SplitGroup, SplitError]:
    def op(session: Session) -> SplitGroup | None:
        return session.query(SplitGroup).filter(SplitGroup.name == name).one_or_none()

    return (
        ctx.run(op)
        .map_err(lambda err: SplitError(str(err)))
        .and_then(lambda group:
            Result.ok(group)
            if group is not None
            else Result.err(SplitGroupNotFound(name))
        )
    )


@crud_retrieve
def splits_in_group_service(ctx: DbTransactionContext, group_id: int) -> Result[list[Split], SplitError]:
    """The group's member splits, with everything the group report reads
    eager-loaded before the session closes (design §6)."""

    def op(session: Session) -> list[Split]:
        return list(
            session.query(Split)
            .filter(Split.group_id == group_id)
            .options(
                selectinload(Split.adjusting_entry)
                .selectinload(JournalEntry.lines)
                .joinedload(JournalLine.account)
            )
            .all()
        )

    return ctx.run(op).map_err(lambda err: SplitError(str(err)))
