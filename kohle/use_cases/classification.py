from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import uuid4

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    AccountNotFoundError,
    ClassifyPlanChanged,
    ClassifyRulesError,
    EntryAlreadySplit,
    JournalError,
    ListUnclassifiedError,
    NoSplitForEntry,
    PostingToNonLeafAccount,
    ReclassifyError,
)
from kohle.domain.models import Classification, JournalEntry
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.account_services import (
    account_has_children_service,
    get_account_by_name_service,
)
from kohle.services.classification_services import (
    classification_by_entry_service,
    rerun_candidates_service,
    set_classification_outcome_service,
    set_rerun_outcome_service,
    unclassified_classifications_service,
)
from kohle.services.journal_services import Counterparty, LineSpec
from kohle.services.split_services import split_by_entry_service
from kohle.use_cases.journal import (
    UNCLASSIFIED_EXPENSE,
    UNCLASSIFIED_INCOME,
    post_entry,
)
from kohle.use_cases.rules import compile_rules, match_rule, stored_rules

# classification.py may import from journal.py (post_entry, the bucket names)
# and reaches split_by_entry_service in the services layer directly, never
# through splitting.py — splitting.py already imports this module's sibling
# services, and importing splitting.py here would close that cycle (design
# §1). journal.py must never import from here — the import loop calls
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
    # entry ever grows past two lines. The account is proposed_account_id, not
    # final_account_id: a line reclassified into a bucket has no entry line on
    # the bucket, while the proposed account's line is always there.
    line = next(line for line in entry.lines if line.account_id == classification.proposed_account_id)
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


def _post_correction(
    ctx: DbTransactionContext, classification: Classification, to_account_id: int, description: str
) -> Result[JournalEntry, JournalError]:
    """Reverse the line out of final_account_id and post it onto the target.

    The one place a line moves between accounts after import. The original
    counterpart line to mirror is located by proposed_account_id: after a
    first move the original entry still carries its line there, not on the
    final account.
    """
    entry = classification.entry
    original_line = next(line for line in entry.lines if line.account_id == classification.proposed_account_id)
    lines = [
        LineSpec(
            classification.final_account_id, original_line.unit_id, original_line.quantity,
            original_line.unit_price, is_debit=not original_line.is_debit,
        ),
        LineSpec(
            to_account_id, original_line.unit_id, original_line.quantity,
            original_line.unit_price, is_debit=original_line.is_debit,
        ),
    ]
    # Dated the original entry's date, not today: balance and
    # entries-in-period are period queries, and dating the correction
    # today would leave the original period permanently misreported.
    return post_entry(ctx, entry.entry_date, uuid4().hex, description, lines)


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
            # A split entry no longer holds its full quantity on
            # final_account_id, so reclassifying it would silently post a
            # wrong balance rather than a correction (design §5.4).
            split_res = split_by_entry_service(ctx, entry_id)
            if split_res.is_ok:
                return Result.err(EntryAlreadySplit(entry_id))
            if not isinstance(split_res.unwrap_err(), NoSplitForEntry):
                return Result.err(split_res.unwrap_err())

            classification_res = classification_by_entry_service(ctx, entry_id)
            if classification_res.is_err:
                return Result.err(classification_res.unwrap_err())
            classification = classification_res.unwrap()

            account_res = get_account_by_name_service(ctx, account_name)
            if account_res.is_err:
                return Result.err(account_res.unwrap_err())
            right_account = account_res.unwrap()

            entry = classification.entry
            adjusting_entry_res = _post_correction(
                ctx, classification, right_account.id, f"Reclassify: {entry.description}"
            )
            if adjusting_entry_res.is_err:
                return Result.err(adjusting_entry_res.unwrap_err())

            outcome_res = set_classification_outcome_service(ctx, classification.id, right_account.id)
            if outcome_res.is_err:
                return Result.err(outcome_res.unwrap_err())

            return Result.ok(adjusting_entry_res.unwrap())

        return self._run(use_case)


@dataclass(frozen=True, slots=True)
class RerunMove:
    """One line classify-rules would move, with what the preview shows."""

    entry_id: int
    entry_date: date
    description: str
    amount: Decimal  # signed, as the rules saw it
    bucket_name: str
    rule_id: int
    account_id: int
    account_name: str

    @property
    def key(self) -> tuple[int, int, int]:
        return (self.entry_id, self.rule_id, self.account_id)


def _rule_amount(classification: Classification) -> Decimal:
    """The signed amount the import gave the rules: the counterpart line is
    debited exactly when the amount was negative."""
    line = next(line for line in classification.entry.lines if line.account_id == classification.proposed_account_id)
    return -line.value if line.is_debit else line.value


def _plan_moves(ctx: DbTransactionContext) -> Result[list[RerunMove], ClassifyRulesError]:
    bucket_ids = []
    for bucket_name in (UNCLASSIFIED_EXPENSE, UNCLASSIFIED_INCOME):
        account_res = get_account_by_name_service(ctx, bucket_name)
        if account_res.is_err:
            err = account_res.unwrap_err()
            if isinstance(err, AccountNotFoundError):
                # Nothing imported yet is emptiness; the strict lookup keeps
                # this read from creating the buckets.
                return Result.ok([])
            return Result.err(err)
        bucket_ids.append(account_res.unwrap().id)

    candidates_res = rerun_candidates_service(ctx, bucket_ids)
    if candidates_res.is_err:
        return Result.err(candidates_res.unwrap_err())
    rules_res = stored_rules(ctx)
    if rules_res.is_err:
        return Result.err(rules_res.unwrap_err())
    rules = rules_res.unwrap()
    compiled = compile_rules(rules)
    account_names = {rule.account_id: rule.account_name for rule in rules}

    moves = []
    for classification in candidates_res.unwrap():
        entry = classification.entry
        counterparty = Counterparty(entry.counterparty_name, entry.counterparty_iban)
        amount = _rule_amount(classification)
        matched = match_rule(compiled, entry.description, counterparty, amount)
        # A rule aimed at the bucket the line is already in moves nothing.
        if matched is None or matched.account_id == classification.final_account_id:
            continue
        moves.append(
            RerunMove(
                entry.id, entry.entry_date, entry.description, amount, classification.final_account.name,
                matched.rule_id, matched.account_id, account_names[matched.account_id],
            )
        )

    # Checked before any preview, so it never promises a move the apply would
    # refuse, and the failure matches the import's.
    for account_id in sorted({move.account_id for move in moves}):
        has_children = account_has_children_service(ctx, account_id)
        if has_children.is_err:
            return Result.err(has_children.unwrap_err())
        if has_children.unwrap():
            return Result.err(PostingToNonLeafAccount(account_id))
    return Result.ok(moves)


class PlanClassifyRules(UnitOfWork[list[RerunMove], ClassifyRulesError]):
    def execute(self) -> Result[list[RerunMove], ClassifyRulesError]:
        return self._run(_plan_moves)


class ApplyClassifyRules(UnitOfWork[list[RerunMove], ClassifyRulesError]):
    def execute(self, expected: list[RerunMove]) -> Result[list[RerunMove], ClassifyRulesError]:
        def use_case(ctx: DbTransactionContext) -> Result[list[RerunMove], ClassifyRulesError]:
            # Re-planned inside the writing transaction: the preview was made in
            # another one, and any import, reclassify or rule change since then
            # shows up as a difference.
            planned = _plan_moves(ctx)
            if planned.is_err:
                return planned
            moves = planned.unwrap()
            if [move.key for move in moves] != [move.key for move in expected]:
                return Result.err(ClassifyPlanChanged())

            for move in moves:
                classification_res = classification_by_entry_service(ctx, move.entry_id)
                if classification_res.is_err:
                    return Result.err(classification_res.unwrap_err())
                classification = classification_res.unwrap()
                posted = _post_correction(ctx, classification, move.account_id, f"Classify: {move.description}")
                if posted.is_err:
                    return Result.err(posted.unwrap_err())
                outcome = set_rerun_outcome_service(ctx, classification.id, move.account_id, move.rule_id)
                if outcome.is_err:
                    return Result.err(outcome.unwrap_err())
            return Result.ok(moves)

        return self._run(use_case)
