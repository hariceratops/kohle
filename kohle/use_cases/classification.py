from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    AccountNotFoundError,
    ClassifyPlanChanged,
    ClassifyRulesError,
    EntryAlreadySplit,
    InvalidTransferTarget,
    IsAMirror,
    RemittanceCompleted,
    ListUnclassifiedError,
    NoSplitForEntry,
    PostingToNonLeafAccount,
    ReclassifyError,
)
from kohle.domain.models import (
    AccountType,
    Classification,
    ClassificationKind,
    JournalEntry,
    RuleKind,
)
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.account_services import (
    account_has_children_service,
    get_account_by_name_service,
    list_accounts_service,
)
from kohle.services.classification_services import (
    classification_by_entry_service,
    mirror_of_service,
    rerun_candidates_service,
    set_classification_outcome_service,
    set_rerun_outcome_service,
    unclassified_classifications_service,
)
from kohle.services.journal_services import Counterparty
from kohle.services.split_services import split_by_entry_service
from kohle.use_cases.accounts import (
    PENDING_REMITTANCES,
    UNCLASSIFIED_EXPENSE,
    UNCLASSIFIED_INCOME,
    get_or_create_account,
    own_account,
    people_account_ids,
)
from kohle.use_cases.posting import post_correction, statement_amount, statement_line
from kohle.use_cases.rules import compile_rules, match_rule, stored_rules
from kohle.use_cases.transfers import (
    TransferSide,
    absorb,
    absorb_counterpart_fall_through,
    account_ibans,
    nearest_row,
    nearest_transfer,
    open_transfers_into,
    row_side,
    unabsorb,
)

# classification.py reaches split_by_entry_service in the services layer
# directly, never through splitting.py — splitting.py already imports this module's sibling
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
            # wrong balance rather than a correction (design §5.4). An undone
            # split keeps its row with no adjusting entry and the full
            # quantity is back, so only a current allocation is refused.
            split_res = split_by_entry_service(ctx, entry_id)
            if split_res.is_ok:
                if split_res.unwrap().adjusting_entry_id is not None:
                    return Result.err(EntryAlreadySplit(entry_id))
            elif not isinstance(split_res.unwrap_err(), NoSplitForEntry):
                return Result.err(split_res.unwrap_err())

            classification_res = classification_by_entry_service(ctx, entry_id)
            if classification_res.is_err:
                return Result.err(classification_res.unwrap_err())
            classification = classification_res.unwrap()

            account_res = get_account_by_name_service(ctx, account_name)
            if account_res.is_err:
                return Result.err(account_res.unwrap_err())
            right_account = account_res.unwrap()

            if classification.kind == ClassificationKind.mirror:
                assert classification.mirror_of_entry_id is not None
                return Result.err(IsAMirror(entry_id, classification.mirror_of_entry_id))
            if classification.completion_entry_id is not None:
                return Result.err(RemittanceCompleted(entry_id, classification.completion_entry_id))

            # The target's type decides the path (design §7.1): an own account
            # is a transfer, anything else is a category.
            people_res = people_account_ids(ctx)
            if people_res.is_err:
                return Result.err(people_res.unwrap_err())
            to_own_account = own_account(right_account, people_res.unwrap())
            if to_own_account:
                if right_account.name == PENDING_REMITTANCES:
                    return Result.err(InvalidTransferTarget(account_name, "it is kohle's pending bucket"))
                if right_account.id == statement_line(classification).account_id:
                    return Result.err(InvalidTransferTarget(account_name, "it is the line's own account"))

            # A transfer taken off its counterpart leaves its mirror with
            # nothing to mirror: the mirror goes back to its bucket first.
            if classification.kind == ClassificationKind.transfer:
                mirror_res = mirror_of_service(ctx, entry_id)
                if mirror_res.is_err:
                    return Result.err(mirror_res.unwrap_err())
                mirror = mirror_res.unwrap()
                if mirror is not None:
                    unabsorbed_res = unabsorb(ctx, mirror, by_human=False)
                    if unabsorbed_res.is_err:
                        return Result.err(unabsorbed_res.unwrap_err())

            entry = classification.entry
            adjusting_entry_res = post_correction(
                ctx, classification, right_account.id, f"Reclassify: {entry.description}"
            )
            if adjusting_entry_res.is_err:
                return Result.err(adjusting_entry_res.unwrap_err())

            kind = ClassificationKind.transfer if to_own_account else ClassificationKind.category
            outcome_res = set_classification_outcome_service(ctx, classification.id, right_account.id, kind)
            if outcome_res.is_err:
                return Result.err(outcome_res.unwrap_err())

            if to_own_account:
                bucket_ids = []
                for bucket_name in (UNCLASSIFIED_EXPENSE, UNCLASSIFIED_INCOME):
                    bucket_res = get_account_by_name_service(ctx, bucket_name)
                    if bucket_res.is_err:
                        return Result.err(bucket_res.unwrap_err())
                    bucket_ids.append(bucket_res.unwrap().id)
                ibans_res = account_ibans(ctx)
                if ibans_res.is_err:
                    return Result.err(ibans_res.unwrap_err())
                absorbed_res = absorb_counterpart_fall_through(ctx, classification, bucket_ids, ibans_res.unwrap())
                if absorbed_res.is_err:
                    return Result.err(absorbed_res.unwrap_err())

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
    rule_id: int | None  # None for a mirror: no rule moved it, a transfer absorbed it
    account_id: int  # where the line goes; for a mirror, its own account
    account_name: str
    kind: ClassificationKind = ClassificationKind.category
    mirror_of: int | None = None
    unit_id: int | None = None
    unit_identifier: str | None = None

    @property
    def key(self) -> tuple[int, int | None, int, ClassificationKind, int | None]:
        return (self.entry_id, self.rule_id, self.account_id, self.kind, self.mirror_of)


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
    candidates = candidates_res.unwrap()
    rules_res = stored_rules(ctx)
    if rules_res.is_err:
        return Result.err(rules_res.unwrap_err())
    compiled = compile_rules(rules_res.unwrap())
    ibans_res = account_ibans(ctx)
    if ibans_res.is_err:
        return Result.err(ibans_res.unwrap_err())
    ibans = ibans_res.unwrap()
    accounts_res = list_accounts_service(ctx)
    if accounts_res.is_err:
        return Result.err(accounts_res.unwrap_err())
    account_names = {account.id: account.name for account in accounts_res.unwrap()}
    unit_identifiers = {rule.unit_id: rule.unit_identifier for rule in rules_res.unwrap() if rule.unit_id is not None}

    by_entry = {c.journal_entry_id: c for c in candidates}
    matches = {}
    for classification in candidates:
        entry = classification.entry
        counterparty = Counterparty(entry.counterparty_name, entry.counterparty_iban)
        matches[entry.id] = match_rule(
            compiled,
            entry.description,
            counterparty,
            statement_amount(classification),
            statement_account_id=statement_line(classification).account_id,
        )

    def move(
        classification: Classification,
        rule_id: int | None,
        account_id: int,
        kind: ClassificationKind,
        mirror_of: int | None = None,
        unit_id: int | None = None,
    ) -> RerunMove:
        entry = classification.entry
        return RerunMove(
            entry.id, entry.entry_date, entry.description, statement_amount(classification),
            classification.final_account.name, rule_id, account_id, account_names[account_id], kind, mirror_of,
            unit_id, unit_identifiers[unit_id] if unit_id is not None else None,
        )

    moves: list[RerunMove] = []
    claimed: set[int] = set()

    # Mirror recognition runs before any rule, so a line that mirrors an
    # existing transfer is absorbed even when a rule would also match it.
    open_by_account: dict[int, list[TransferSide]] = {}
    for classification in candidates:
        account_id = statement_line(classification).account_id
        if account_id not in open_by_account:
            open_res = open_transfers_into(ctx, account_id, ibans)
            if open_res.is_err:
                return Result.err(open_res.unwrap_err())
            open_by_account[account_id] = open_res.unwrap()
        pool = open_by_account[account_id]
        hit = nearest_transfer(row_side(classification), pool)
        if hit is not None:
            pool.remove(hit)
            claimed.add(classification.journal_entry_id)
            moves.append(move(classification, None, account_id, ClassificationKind.mirror, hit.entry_id))

    # A transfer move takes its counterpart's nearest fall-through with it, so
    # with symmetric rules the earlier line makes the move and absorbs the other.
    for classification in candidates:
        matched = matches[classification.journal_entry_id]
        if classification.journal_entry_id in claimed or matched is None or matched.kind is not RuleKind.transfer:
            continue
        claimed.add(classification.journal_entry_id)
        moves.append(move(classification, matched.rule_id, matched.account_id, ClassificationKind.transfer))
        side = TransferSide(
            classification.entry.id,
            classification.entry.entry_date,
            statement_amount(classification),
            matched.account_id,
            ibans[statement_line(classification).account_id],
        )
        rows = [
            (other.journal_entry_id, row_side(other))
            for other in candidates
            if other.journal_entry_id not in claimed and statement_line(other).account_id == matched.account_id
        ]
        picked = nearest_row(side, rows)
        if picked is not None:
            claimed.add(picked)
            moves.append(
                move(by_entry[picked], None, matched.account_id, ClassificationKind.mirror, side.entry_id)
            )

    for classification in candidates:
        matched = matches[classification.journal_entry_id]
        # A rule aimed at the bucket the line is already in moves nothing.
        if (
            classification.journal_entry_id in claimed
            or matched is None
            or matched.account_id == classification.final_account_id
        ):
            continue
        kind = ClassificationKind(matched.kind.value)
        moves.append(move(classification, matched.rule_id, matched.account_id, kind, unit_id=matched.unit_id))

    # Checked before any preview, so it never promises a move the apply would
    # refuse, and the failure matches the import's. A mirror goes to the
    # account its statement was imported into, which is never a rule's target,
    # and a remittance goes to the pending bucket, which kohle makes a leaf.
    unchecked = (ClassificationKind.mirror, ClassificationKind.remittance)
    for account_id in sorted({m.account_id for m in moves if m.kind not in unchecked}):
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

            pending_id: int | None = None
            for move in moves:
                classification_res = classification_by_entry_service(ctx, move.entry_id)
                if classification_res.is_err:
                    return Result.err(classification_res.unwrap_err())
                classification = classification_res.unwrap()
                if move.kind is ClassificationKind.mirror:
                    assert move.mirror_of is not None
                    absorbed = absorb(ctx, classification, move.mirror_of, by_human=False)
                    if absorbed.is_err:
                        return Result.err(absorbed.unwrap_err())
                    continue
                assert move.rule_id is not None
                target_id = move.account_id
                if move.kind is ClassificationKind.remittance:
                    if pending_id is None:
                        pending_res = get_or_create_account(ctx, PENDING_REMITTANCES, AccountType.asset)
                        if pending_res.is_err:
                            return Result.err(pending_res.unwrap_err())
                        pending_id = pending_res.unwrap().id
                    target_id = pending_id
                posted = post_correction(ctx, classification, target_id, f"Classify: {move.description}")
                if posted.is_err:
                    return Result.err(posted.unwrap_err())
                remitted = move.kind is ClassificationKind.remittance
                outcome = set_rerun_outcome_service(
                    ctx,
                    classification.id,
                    target_id,
                    move.rule_id,
                    kind=move.kind,
                    remittance_account_id=move.account_id if remitted else None,
                    remittance_unit_id=move.unit_id,
                )
                if outcome.is_err:
                    return Result.err(outcome.unwrap_err())
            return Result.ok(moves)

        return self._run(use_case)
