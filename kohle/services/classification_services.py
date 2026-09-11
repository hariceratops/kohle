from sqlalchemy.orm import Session

from kohle.core.result import Result
from kohle.domain.domain_errors import ClassificationError
from kohle.domain.models import Classification
from kohle.infrastructure.crud import crud_create
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
