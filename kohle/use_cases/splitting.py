from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    JournalError,
    NoSplitForEntry,
    NotAPersonAccount,
    SplitDoesNotSumToLine,
    SplitError,
    SplitImportedEntryError,
)
from kohle.domain.models import JournalEntry
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.account_services import (
    descendant_account_ids_service,
    get_account_by_name_service,
)
from kohle.services.classification_services import classification_by_entry_service
from kohle.services.journal_services import LineSpec
from kohle.services.split_services import (
    set_split_adjusting_entry_service,
    split_by_entry_service,
)
from kohle.use_cases.journal import PEOPLE_ROOT, post_entry

UnsplitEntryError = JournalError | SplitError

# splitting.py may import from journal.py (post_entry, PEOPLE_ROOT) and reach
# classification_by_entry_service in the services layer directly; journal.py
# must never import from here — the same import-direction rule
# classification.py follows, for the same reason (design §1).


@dataclass(frozen=True, slots=True)
class PersonShare:
    person_name: str
    quantity: Decimal


class SplitImportedEntry(UnitOfWork[JournalEntry, SplitImportedEntryError]):
    """Divides an already-imported line between the user's own share and one
    or more person accounts, by reversing the line's current allocation and
    re-posting it split (design §4.3) — the `Reclassify` precedent applied to
    a division rather than a move. The original entry is never edited, voided
    or deleted.
    """

    def execute(
        self, entry_id: int, own_share: Decimal, shares: Iterable[PersonShare]
    ) -> Result[JournalEntry, SplitImportedEntryError]:
        def use_case(ctx: DbTransactionContext) -> Result[JournalEntry, SplitImportedEntryError]:
            classification_res = classification_by_entry_service(ctx, entry_id)
            if classification_res.is_err:
                return Result.err(classification_res.unwrap_err())
            classification = classification_res.unwrap()

            entry = classification.entry
            # Located by proposed_account_id: the entry always carries its
            # counterpart line on the account first proposed, even after a
            # correction moved the value elsewhere (design §4.2).
            original_line = next(
                line for line in entry.lines if line.account_id == classification.proposed_account_id
            )
            # Where the value sits now, not where it first landed — splitting
            # a reclassified line takes the shares out of its corrected
            # account, not out of the bucket a second time (design §4.2).
            current_account_id = classification.final_account_id

            people_res = get_account_by_name_service(ctx, PEOPLE_ROOT)
            if people_res.is_err:
                return Result.err(people_res.unwrap_err())
            people_ids_res = descendant_account_ids_service(ctx, people_res.unwrap().id)
            if people_ids_res.is_err:
                return Result.err(people_ids_res.unwrap_err())
            people_ids = set(people_ids_res.unwrap())

            share_lines: list[LineSpec] = []
            total_shares = Decimal(0)
            for share in shares:
                account_res = get_account_by_name_service(ctx, share.person_name)
                if account_res.is_err:
                    return Result.err(account_res.unwrap_err())
                person_account = account_res.unwrap()
                if person_account.id not in people_ids:
                    return Result.err(NotAPersonAccount(share.person_name))

                total_shares += share.quantity
                share_lines.append(
                    LineSpec(
                        person_account.id, original_line.unit_id, share.quantity,
                        original_line.unit_price, is_debit=original_line.is_debit,
                    )
                )

            if own_share + total_shares != original_line.quantity:
                return Result.err(SplitDoesNotSumToLine(original_line.quantity, own_share + total_shares))

            lines = [
                LineSpec(
                    current_account_id, original_line.unit_id, original_line.quantity,
                    original_line.unit_price, is_debit=not original_line.is_debit,
                ),
            ]
            # A zero-quantity line carries no information; --mine 0 is a
            # legitimate case (you paid entirely for someone else) and must
            # not post an empty line for it (design §4.3).
            if own_share != 0:
                lines.append(
                    LineSpec(
                        current_account_id, original_line.unit_id, own_share,
                        original_line.unit_price, is_debit=original_line.is_debit,
                    )
                )
            lines.extend(share_lines)

            # Re-splitting an already-split entry is an edit, not a refusal
            # (design §5.3): mirror the current allocation away first, in the
            # same transaction, before posting the new one. A split that was
            # already undone (adjusting_entry_id IS NULL) has nothing to
            # mirror and is treated as a fresh split.
            existing_res = split_by_entry_service(ctx, entry_id)
            if existing_res.is_err and not isinstance(existing_res.unwrap_err(), NoSplitForEntry):
                return Result.err(existing_res.unwrap_err())
            if existing_res.is_ok and existing_res.unwrap().adjusting_entry_id is not None:
                unsplit_res = _post_unsplit_entry(ctx, entry, existing_res.unwrap().adjusting_entry)
                if unsplit_res.is_err:
                    return Result.err(unsplit_res.unwrap_err())

            # Dated the original entry's date, not today — the same reasoning
            # Reclassify's adjusting entry follows.
            adjusting_entry_res = post_entry(
                ctx, entry.entry_date, uuid4().hex, f"Split: {entry.description}", lines
            )
            if adjusting_entry_res.is_err:
                return Result.err(adjusting_entry_res.unwrap_err())
            adjusting_entry = adjusting_entry_res.unwrap()

            split_res = set_split_adjusting_entry_service(ctx, entry_id, adjusting_entry.id)
            if split_res.is_err:
                return Result.err(split_res.unwrap_err())

            return Result.ok(adjusting_entry)

        return self._run(use_case)


def _post_unsplit_entry(
    ctx: DbTransactionContext, entry: JournalEntry, adjusting_entry: JournalEntry
) -> Result[JournalEntry, JournalError]:
    """Mirrors an adjusting entry's lines with every side flipped — same
    accounts, units, quantities and prices, opposite sides. Because the split
    entry states the complete allocation, mirroring it restores the pre-split
    state exactly with no arithmetic (design §5.1). Shared by `UnsplitEntry`
    and the edit path in `SplitImportedEntry`, which mirrors the *existing*
    adjusting entry before posting the new one (design §5.3).
    """
    lines = [
        LineSpec(
            line.account_id, line.unit_id, line.quantity, line.unit_price, is_debit=not line.is_debit,
        )
        for line in adjusting_entry.lines
    ]
    return post_entry(ctx, entry.entry_date, uuid4().hex, f"Unsplit: {entry.description}", lines)


class UnsplitEntry(UnitOfWork[JournalEntry, UnsplitEntryError]):
    """Undoes a previously-recorded split by mirroring its current adjusting
    entry, restoring the expense account and person account balances to what
    they were before the split (design §5.1). The `splits` row survives with
    `adjusting_entry_id` set to NULL rather than being deleted or
    soft-deleted, keeping "the split of this line" a single referent for any
    later `split-line` on the same entry (design §4.4).
    """

    def execute(self, entry_id: int) -> Result[JournalEntry, UnsplitEntryError]:
        def use_case(ctx: DbTransactionContext) -> Result[JournalEntry, UnsplitEntryError]:
            split_res = split_by_entry_service(ctx, entry_id)
            if split_res.is_err:
                return Result.err(split_res.unwrap_err())
            split = split_res.unwrap()
            # An entry that was split and then undone already has
            # adjusting_entry_id IS NULL — there is no current split to
            # undo, and that is the same NoSplitForEntry an unknown
            # reference gets (design §5.1).
            if split.adjusting_entry_id is None:
                return Result.err(NoSplitForEntry(entry_id))

            mirror_res = _post_unsplit_entry(ctx, split.entry, split.adjusting_entry)
            if mirror_res.is_err:
                return Result.err(mirror_res.unwrap_err())

            update_res = set_split_adjusting_entry_service(ctx, entry_id, None)
            if update_res.is_err:
                return Result.err(update_res.unwrap_err())

            return Result.ok(mirror_res.unwrap())

        return self._run(use_case)
