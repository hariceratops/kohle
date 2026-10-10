from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import uuid4

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    AccountNotFoundError,
    ListUnclassifiedError,
    ReclassifyError,
)
from kohle.domain.models import Classification, JournalEntry
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.account_services import get_account_by_name_service
from kohle.services.classification_services import (
    classification_by_entry_service,
    set_classification_outcome_service,
    unclassified_classifications_service,
)
from kohle.services.journal_services import LineSpec
from kohle.use_cases.journal import (
    UNCLASSIFIED_EXPENSE,
    UNCLASSIFIED_INCOME,
    post_entry,
)

# classification.py may import from journal.py (post_entry, the bucket names);
# journal.py must never import from here — the import loop calls
# add_classification_service directly in the services layer instead of
# routing through a use case in this module (design §1).


@dataclass(frozen=True, slots=True)
class UnclassifiedLine:
    """Everything list-unclassified renders, plus the id reclassify takes.

    ORM instances cannot cross this boundary — the session closes before the
    CLI reads the result (design §6.3) — so this is the shape that does.
    """

    entry_id: int
    entry_date: date
    description: str
    counterparty_name: str | None
    counterparty_iban: str | None
    amount: Decimal
    account_name: str


def _to_unclassified_line(classification: Classification) -> UnclassifiedLine:
    entry = classification.entry
    # Both lines of an import entry carry the same value by construction, but
    # picking the line by account rather than by position stays correct if an
    # entry ever grows past two lines.
    line = next(line for line in entry.lines if line.account_id == classification.final_account_id)
    return UnclassifiedLine(
        entry_id=entry.id,
        entry_date=entry.entry_date,
        description=entry.description,
        counterparty_name=entry.counterparty_name,
        counterparty_iban=entry.counterparty_iban,
        amount=line.value,
        account_name=classification.final_account.name,
    )


class ListUnclassified(UnitOfWork[list[UnclassifiedLine], ListUnclassifiedError]):
    def execute(self) -> Result[list[UnclassifiedLine], ListUnclassifiedError]:
        def use_case(ctx: DbTransactionContext) -> Result[list[UnclassifiedLine], ListUnclassifiedError]:
            bucket_ids = []
            for bucket_name in (UNCLASSIFIED_EXPENSE, UNCLASSIFIED_INCOME):
                account_res = get_account_by_name_service(ctx, bucket_name)
                if account_res.is_err:
                    err = account_res.unwrap_err()
                    if isinstance(err, AccountNotFoundError):
                        # Neither bucket exists until the first import creates
                        # them, using the strict lookup rather than
                        # _get_or_create_account so this read-only command
                        # writes nothing (design §6.2). Nothing imported yet
                        # is emptiness, not an error.
                        return Result.ok([])
                    return Result.err(err)
                bucket_ids.append(account_res.unwrap().id)

            return unclassified_classifications_service(ctx, bucket_ids).map(
                lambda classifications: [_to_unclassified_line(c) for c in classifications]
            )

        return self._run(use_case)


class Reclassify(UnitOfWork[JournalEntry, ReclassifyError]):
    """Corrects a classified line by posting a reversing pair, never by
    editing the original entry (design §7.1).

    Mirrors the original counterpart line rather than branching on
    expense/income: crediting what it debited and vice versa handles both
    directions with one expression. The line being reversed out of is
    final_account_id, not proposed_account_id, so a second correction
    (A -> B, then B -> C) reverses out of B rather than out of the bucket a
    second time; the counterpart line to mirror is located by
    proposed_account_id because after a first correction the original entry
    still carries its line on the proposed account, not the final one.
    """

    def execute(self, entry_id: int, account_name: str) -> Result[JournalEntry, ReclassifyError]:
        def use_case(ctx: DbTransactionContext) -> Result[JournalEntry, ReclassifyError]:
            classification_res = classification_by_entry_service(ctx, entry_id)
            if classification_res.is_err:
                return Result.err(classification_res.unwrap_err())
            classification = classification_res.unwrap()

            account_res = get_account_by_name_service(ctx, account_name)
            if account_res.is_err:
                return Result.err(account_res.unwrap_err())
            right_account = account_res.unwrap()

            entry = classification.entry
            original_line = next(
                line for line in entry.lines if line.account_id == classification.proposed_account_id
            )
            wrong_account_id = classification.final_account_id

            lines = [
                LineSpec(
                    wrong_account_id, original_line.unit_id, original_line.quantity,
                    original_line.unit_price, is_debit=not original_line.is_debit,
                ),
                LineSpec(
                    right_account.id, original_line.unit_id, original_line.quantity,
                    original_line.unit_price, is_debit=original_line.is_debit,
                ),
            ]

            # Dated the original entry's date, not today: balance and
            # entries-in-period are period queries, and dating the correction
            # today would leave the original period permanently misreported.
            adjusting_entry_res = post_entry(
                ctx, entry.entry_date, uuid4().hex, f"Reclassify: {entry.description}", lines
            )
            if adjusting_entry_res.is_err:
                return Result.err(adjusting_entry_res.unwrap_err())

            outcome_res = set_classification_outcome_service(ctx, classification.id, right_account.id)
            if outcome_res.is_err:
                return Result.err(outcome_res.unwrap_err())

            return Result.ok(adjusting_entry_res.unwrap())

        return self._run(use_case)
