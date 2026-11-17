from collections.abc import Iterable
from datetime import date

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from kohle.core.result import Result
from kohle.domain.domain_errors import ClassificationError, NoClassificationForEntry
from kohle.domain.models import (
    Classification,
    ClassificationKind,
    JournalEntry,
    JournalLine,
    Split,
)
from kohle.infrastructure.crud import crud_create, crud_retrieve, crud_update
from kohle.infrastructure.transaction_context import DbTransactionContext


@crud_create
def add_classification_service(
    ctx: DbTransactionContext,
    journal_entry_id: int,
    proposed_account_id: int,
    matched_rule_id: int | None,
    final_account_id: int,
    kind: ClassificationKind = ClassificationKind.category,
) -> Result[Classification, ClassificationError]:
    """Record one classification decision.

    Takes a ctx rather than opening its own transaction: the import loop calls
    this once per row, and a unit of work here would commit and close the
    session on the first row, half-committing the statement (design §5.2).
    """

    def op(session: Session) -> Classification:
        classification = Classification(
            journal_entry_id=journal_entry_id,
            proposed_account_id=proposed_account_id,
            matched_rule_id=matched_rule_id,
            final_account_id=final_account_id,
            kind=kind,
        )
        session.add(classification)
        return classification

    return ctx.run(op).map_err(lambda err: ClassificationError(str(err)))


@crud_retrieve
def classification_by_entry_service(
    ctx: DbTransactionContext, journal_entry_id: int
) -> Result[Classification, ClassificationError]:
    """The one classification row for a journal entry — reclassify's lookup.

    joinedload for the entry (scalar), selectinload for its lines
    (collection): the same reasoning as unclassified_classifications_service
    below, and reclassify needs the original counterpart line loaded before
    the session closes.
    """

    def op(session: Session) -> Classification | None:
        return (
            session.query(Classification)
            .options(joinedload(Classification.entry).selectinload(JournalEntry.lines))
            .filter(Classification.journal_entry_id == journal_entry_id)
            .one_or_none()
        )

    return (
        ctx.run(op)
        .map_err(lambda err: ClassificationError(str(err)))
        .and_then(lambda classification:
            Result.ok(classification)
            if classification is not None
            else Result.err(NoClassificationForEntry(journal_entry_id))
        )
    )


@crud_update
def set_classification_outcome_service(
    ctx: DbTransactionContext,
    classification_id: int,
    final_account_id: int,
    kind: ClassificationKind = ClassificationKind.category,
) -> Result[Classification, ClassificationError]:
    """Correct the record: final_account_id and kind move, corrected is set.

    proposed_account_id and matched_rule_id are left untouched — they are the
    record of what the engine got wrong, which is the reason they exist
    (design §7.2).
    """

    def op(session: Session) -> Classification | None:
        classification = session.get(Classification, classification_id)
        if classification is not None:
            classification.final_account_id = final_account_id
            classification.kind = kind
            classification.corrected = True
        return classification

    return (
        ctx.run(op)
        .map_err(lambda err: ClassificationError(str(err)))
        .and_then(lambda classification:
            Result.ok(classification)
            if classification is not None
            else Result.err(ClassificationError(f"Classification id {classification_id} not found"))
        )
    )


@crud_retrieve
def unclassified_classifications_service(
    ctx: DbTransactionContext, bucket_account_ids: Iterable[int]
) -> Result[list[Classification], ClassificationError]:
    """Classifications still sitting on one of the unclassified buckets.

    Filters on final_account_id rather than matched_rule_id IS NULL: a
    corrected fall-through row still has no matched rule, but its final
    account has moved off the bucket, and that move — not the rule
    attribution — is what makes it no longer unclassified (design §6.1).
    """

    def op(session: Session) -> list[Classification]:
        return (
            session.query(Classification)
            .join(JournalEntry, Classification.journal_entry_id == JournalEntry.id)
            .options(
                # joinedload for the scalar, selectinload for the collection:
                # a joinedload across both would cartesian-expand the row set
                # for SQLAlchemy to then de-duplicate, which is wasted I/O.
                joinedload(Classification.final_account),
                selectinload(Classification.entry).selectinload(JournalEntry.lines),
            )
            .filter(Classification.final_account_id.in_(list(bucket_account_ids)))
            .order_by(JournalEntry.entry_date.asc(), Classification.journal_entry_id.asc())
            .all()
        )

    return ctx.run(op).map_err(lambda err: ClassificationError(str(err)))


@crud_update
def set_rerun_outcome_service(
    ctx: DbTransactionContext,
    classification_id: int,
    final_account_id: int,
    rule_id: int,
    kind: ClassificationKind = ClassificationKind.category,
) -> Result[Classification, ClassificationError]:
    """Record a classify-rules move: final_account_id, rerun_rule_id and kind
    are set, corrected stays false because no human made the call.

    proposed_account_id and matched_rule_id are untouched: reclassify and
    split-line locate the original line through proposed_account_id."""

    def op(session: Session) -> Classification | None:
        classification = session.get(Classification, classification_id)
        if classification is not None:
            classification.final_account_id = final_account_id
            classification.rerun_rule_id = rule_id
            classification.kind = kind
        return classification

    return (
        ctx.run(op)
        .map_err(lambda err: ClassificationError(str(err)))
        .and_then(lambda classification:
            Result.ok(classification)
            if classification is not None
            else Result.err(ClassificationError(f"Classification id {classification_id} not found"))
        )
    )


@crud_retrieve
def rerun_candidates_service(
    ctx: DbTransactionContext, bucket_account_ids: Iterable[int], statement_account_id: int | None = None
) -> Result[list[Classification], ClassificationError]:
    """The untouched fall-throughs: still on a bucket, and neither a rule nor
    a human nor an earlier classify-rules run has decided them. Split lines
    are left out because reclassify refuses them (the bucket no longer holds
    the full amount).

    With `statement_account_id`, only those imported into that account: the
    entry has a line there that is not the counterpart line."""

    def op(session: Session) -> list[Classification]:
        query = (
            session.query(Classification)
            .join(JournalEntry, Classification.journal_entry_id == JournalEntry.id)
            .options(
                joinedload(Classification.final_account),
                selectinload(Classification.entry).selectinload(JournalEntry.lines),
            )
            .filter(
                Classification.final_account_id.in_(list(bucket_account_ids)),
                Classification.matched_rule_id.is_(None),
                Classification.rerun_rule_id.is_(None),
                Classification.corrected.is_(False),
                ~exists().where(Split.journal_entry_id == Classification.journal_entry_id),
            )
        )
        if statement_account_id is not None:
            query = query.filter(
                exists().where(
                    and_(
                        JournalLine.entry_id == Classification.journal_entry_id,
                        JournalLine.account_id == statement_account_id,
                        JournalLine.account_id != Classification.proposed_account_id,
                    )
                )
            )
        return query.order_by(JournalEntry.entry_date.asc(), Classification.journal_entry_id.asc()).all()

    return ctx.run(op).map_err(lambda err: ClassificationError(str(err)))


@crud_update
def set_mirror_service(
    ctx: DbTransactionContext,
    classification_id: int,
    final_account_id: int,
    mirror_of_entry_id: int,
    by_human: bool,
) -> Result[Classification, ClassificationError]:
    """The line is the other side of a transfer: its own posting is cancelled
    onto `final_account_id`, and the transfer is named by the entry id of its
    statement line. `corrected` is set only when a human made the call."""

    def op(session: Session) -> Classification | None:
        classification = session.get(Classification, classification_id)
        if classification is not None:
            classification.kind = ClassificationKind.mirror
            classification.final_account_id = final_account_id
            classification.mirror_of_entry_id = mirror_of_entry_id
            classification.corrected = classification.corrected or by_human
        return classification

    return (
        ctx.run(op)
        .map_err(lambda err: ClassificationError(str(err)))
        .and_then(lambda classification:
            Result.ok(classification)
            if classification is not None
            else Result.err(ClassificationError(f"Classification id {classification_id} not found"))
        )
    )


@crud_retrieve
def open_transfers_service(
    ctx: DbTransactionContext, counterpart_id: int | None = None
) -> Result[list[Classification], ClassificationError]:
    """Transfers (into `counterpart_id`, when given) that no row has been
    absorbed into yet, in `(entry_date, entry id)` order, with the entry and
    its lines loaded."""

    def op(session: Session) -> list[Classification]:
        joined = select(Classification.mirror_of_entry_id).where(Classification.mirror_of_entry_id.is_not(None))
        query = (
            session.query(Classification)
            .join(JournalEntry, Classification.journal_entry_id == JournalEntry.id)
            .options(selectinload(Classification.entry).selectinload(JournalEntry.lines))
            .filter(
                Classification.kind == ClassificationKind.transfer,
                Classification.journal_entry_id.not_in(joined),
            )
        )
        if counterpart_id is not None:
            query = query.filter(Classification.final_account_id == counterpart_id)
        return query.order_by(JournalEntry.entry_date.asc(), Classification.journal_entry_id.asc()).all()

    return ctx.run(op).map_err(lambda err: ClassificationError(str(err)))


@crud_retrieve
def first_statement_dates_service(
    ctx: DbTransactionContext, account_ids: Iterable[int]
) -> Result[dict[int, date], ClassificationError]:
    """For each of `account_ids` that is the statement account of some
    classification, the earliest entry date of such a row.

    The statement account is the entry's line that is not on
    proposed_account_id, so a transfer's counterpart is not mistaken for the
    account the row was imported into.
    """

    def op(session: Session) -> dict[int, date]:
        rows = (
            session.query(JournalLine.account_id, func.min(JournalEntry.entry_date))
            .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
            .join(Classification, Classification.journal_entry_id == JournalEntry.id)
            .filter(
                JournalLine.account_id.in_(list(account_ids)),
                JournalLine.account_id != Classification.proposed_account_id,
            )
            .group_by(JournalLine.account_id)
            .all()
        )
        return {account_id: first for account_id, first in rows}

    return ctx.run(op).map_err(lambda err: ClassificationError(str(err)))


@crud_update
def clear_mirror_service(
    ctx: DbTransactionContext, classification_id: int, final_account_id: int, by_human: bool
) -> Result[Classification, ClassificationError]:
    """The line is no longer the other side of a transfer: its own posting is
    back on `final_account_id`. `corrected` is set only when a human made the
    call."""

    def op(session: Session) -> Classification | None:
        classification = session.get(Classification, classification_id)
        if classification is not None:
            classification.kind = ClassificationKind.category
            classification.final_account_id = final_account_id
            classification.mirror_of_entry_id = None
            classification.corrected = classification.corrected or by_human
        return classification

    return (
        ctx.run(op)
        .map_err(lambda err: ClassificationError(str(err)))
        .and_then(lambda classification:
            Result.ok(classification)
            if classification is not None
            else Result.err(ClassificationError(f"Classification id {classification_id} not found"))
        )
    )


@crud_retrieve
def mirror_of_service(
    ctx: DbTransactionContext, transfer_entry_id: int
) -> Result[Classification | None, ClassificationError]:
    """The classification of the row absorbed into the transfer, or None."""

    def op(session: Session) -> Classification | None:
        return (
            session.query(Classification)
            .filter(Classification.mirror_of_entry_id == transfer_entry_id)
            .one_or_none()
        )

    return ctx.run(op).map_err(lambda err: ClassificationError(str(err)))
