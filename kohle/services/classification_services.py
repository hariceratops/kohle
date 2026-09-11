from collections.abc import Iterable

from sqlalchemy.orm import Session, joinedload, selectinload

from kohle.core.result import Result
from kohle.domain.domain_errors import ClassificationError
from kohle.domain.models import Classification, JournalEntry
from kohle.infrastructure.crud import crud_create, crud_retrieve
from kohle.infrastructure.transaction_context import DbTransactionContext


@crud_create
def add_classification_service(
    ctx: DbTransactionContext,
    journal_entry_id: int,
    proposed_account_id: int,
    matched_rule_id: int | None,
    final_account_id: int,
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
        )
        session.add(classification)
        return classification

    return ctx.run(op).map_err(lambda err: ClassificationError(str(err)))


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
