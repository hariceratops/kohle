from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from kohle.core.result import Result
from kohle.domain.domain_errors import (
    AccountError,
    EmptySplitGroupName,
    JournalError,
    NoSplitForEntry,
    NotAPersonAccount,
    SplitDoesNotSumToLine,
    SplitError,
    SplitImportedEntryError,
)
from kohle.domain.models import JournalEntry, JournalLine, SplitGroup
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.account_services import (
    descendant_account_ids_service,
    get_account_by_name_service,
    list_child_accounts_service,
)
from kohle.services.classification_services import classification_by_entry_service
from kohle.services.journal_services import LineSpec
from kohle.services.split_services import (
    add_split_group_service,
    get_split_group_by_name_service,
    list_split_groups_service,
    set_split_adjusting_entry_service,
    set_split_group_service,
    split_by_entry_service,
    splits_in_group_service,
)
from kohle.use_cases.journal import (
    PEOPLE_ROOT,
    UnitBalance,
    account_balance,
    aggregate_by_unit,
    post_entry,
)

UnsplitEntryError = JournalError | SplitError
WhoOwesWhatError = AccountError | JournalError | SplitError

# splitting.py may import from journal.py (post_entry, PEOPLE_ROOT) and reach
# classification_by_entry_service in the services layer directly; journal.py
# must never import from here — the same import-direction rule
# classification.py follows, for the same reason (design §1).


@dataclass(frozen=True, slots=True)
class PersonShare:
    person_name: str
    quantity: Decimal


class AddSplitGroup(UnitOfWork[SplitGroup, SplitError]):
    """Creates a trip/label splits can be tagged under (design §2.2, §6).
    Groups are created explicitly and looked up strictly — `split-line
    --group` never auto-vivifies a group from a typo, the same rule that
    makes a typo in `--from` an error rather than a new account."""

    def execute(self, name: str) -> Result[SplitGroup, SplitError]:
        def use_case(ctx: DbTransactionContext) -> Result[SplitGroup, SplitError]:
            text = name.strip()
            if not text:
                return Result.err(EmptySplitGroupName())
            return add_split_group_service(ctx, text)

        return self._run(use_case)


class SplitImportedEntry(UnitOfWork[JournalEntry, SplitImportedEntryError]):
    """Divides an already-imported line between the user's own share and one
    or more person accounts, by reversing the line's current allocation and
    re-posting it split (design §4.3) — the `Reclassify` precedent applied to
    a division rather than a move. The original entry is never edited, voided
    or deleted.
    """

    def execute(
        self,
        entry_id: int,
        own_share: Decimal,
        shares: Iterable[PersonShare],
        group_name: str | None = None,
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

            # --group is authoritative on every run: absent, it clears the
            # group; given, it resolves strictly and sets or moves it
            # (design §5.3). A typo does not create a second group.
            group_id: int | None = None
            if group_name is not None:
                group_res = get_split_group_by_name_service(ctx, group_name)
                if group_res.is_err:
                    return Result.err(group_res.unwrap_err())
                group_id = group_res.unwrap().id
            group_set_res = set_split_group_service(ctx, entry_id, group_id)
            if group_set_res.is_err:
                return Result.err(group_set_res.unwrap_err())

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


@dataclass(frozen=True, slots=True)
class PersonBalance:
    person_name: str
    balances: list[UnitBalance]


@dataclass(frozen=True, slots=True)
class GroupAllocation:
    group_name: str
    allocations: list[PersonBalance]


def _person_balances(ctx: DbTransactionContext) -> Result[list[PersonBalance], WhoOwesWhatError]:
    """Every person account's current balance, by unit — the shared read
    behind `WhoOwesWhat` and `SettleUp`'s global (unscoped) participant set
    (design §7.1, §8.2). Every person account is listed, including one with
    no lines: driven by the account tree rather than by the lines, a settled
    person (their lines cancel) gets a UnitBalance with quantity 0, and a
    person never split against gets an empty balances list — the
    distinction issue 022's last criterion asks for."""
    people_res = get_account_by_name_service(ctx, PEOPLE_ROOT)
    if people_res.is_err:
        return Result.err(people_res.unwrap_err())

    children_res = list_child_accounts_service(ctx, people_res.unwrap().id)
    if children_res.is_err:
        return Result.err(children_res.unwrap_err())

    balances: list[PersonBalance] = []
    for person in children_res.unwrap():
        balance_res = account_balance(ctx, person.id)
        if balance_res.is_err:
            return Result.err(balance_res.unwrap_err())
        balances.append(PersonBalance(person.name, balance_res.unwrap()))

    return Result.ok(balances)


class WhoOwesWhat(UnitOfWork[list[PersonBalance], WhoOwesWhatError]):
    """The net balance of every person account — the same figure `balance
    Alice` gives, listed for the whole People branch at once (design §7.1).
    See `_person_balances` for what "every person account" and "balance"
    mean here.
    """

    def execute(self) -> Result[list[PersonBalance], WhoOwesWhatError]:
        return self._run(_person_balances)


class WhoOwesWhatByGroup(UnitOfWork[list[GroupAllocation], WhoOwesWhatError]):
    """The per-group breakdown behind `who-owes-what --by-group` (design
    §7.2): one block per group, including a group with no splits, so the
    report doubles as the group listing (design §2.2). Splits with no group
    appear in neither block and are unaffected in the global view.

    Computed from the current adjusting entries only — a split that has
    been undone (adjusting_entry_id IS NULL) contributes nothing (design
    §6) — and it is **not** the same figure `WhoOwesWhat` reports: it is a
    historical allocation, not a live, settlement-adjusted balance (design
    §2.3, §7.2).
    """

    def execute(self) -> Result[list[GroupAllocation], WhoOwesWhatError]:
        def use_case(ctx: DbTransactionContext) -> Result[list[GroupAllocation], WhoOwesWhatError]:
            people_res = get_account_by_name_service(ctx, PEOPLE_ROOT)
            if people_res.is_err:
                return Result.err(people_res.unwrap_err())
            people_ids_res = descendant_account_ids_service(ctx, people_res.unwrap().id)
            if people_ids_res.is_err:
                return Result.err(people_ids_res.unwrap_err())
            people_ids = set(people_ids_res.unwrap())

            groups_res = list_split_groups_service(ctx)
            if groups_res.is_err:
                return Result.err(groups_res.unwrap_err())

            report: list[GroupAllocation] = []
            for group in groups_res.unwrap():
                splits_res = splits_in_group_service(ctx, group.id)
                if splits_res.is_err:
                    return Result.err(splits_res.unwrap_err())

                lines_by_person: dict[str, list[JournalLine]] = {}
                for split in splits_res.unwrap():
                    if split.adjusting_entry_id is None:
                        continue
                    for line in split.adjusting_entry.lines:
                        if line.account_id not in people_ids:
                            continue
                        lines_by_person.setdefault(line.account.name, []).append(line)

                allocations = [
                    # (entry_date, line id), matching account_lines_service's
                    # order — aggregate_by_unit's fold is order-dependent
                    # (design §6.4) and these lines come from an eager-loaded
                    # collection with no ordering guarantee of its own.
                    PersonBalance(
                        person_name,
                        aggregate_by_unit(sorted(lines, key=lambda line: (line.entry.entry_date, line.id))),
                    )
                    for person_name, lines in sorted(lines_by_person.items())
                ]
                report.append(GroupAllocation(group.name, allocations))

            return Result.ok(report)

        return self._run(use_case)


SettleUpError = WhoOwesWhatError


@dataclass(frozen=True, slots=True)
class SuggestedTransfer:
    payer: str | None
    payee: str | None
    unit_identifier: str
    quantity: Decimal


def settle(positions: Mapping[str | None, Decimal]) -> list[tuple[str | None, str | None, Decimal]]:
    """Debt-simplification netting for one unit (design §8.1): pure and
    DB-free, the same treatment `match_rule` and `aggregate_by_unit` already
    get, for the same reason.

    `positions` maps participant (`None` is you) to the net amount they must
    pay out — positive owes, negative is owed — and sums to exactly zero by
    construction (§2.3), which is what guarantees this terminates with every
    participant at zero rather than at a residue.

    Greedy max-payer / max-receiver: repeatedly take the largest positive and
    the largest negative position, emit a transfer of `min(payer, -receiver)`,
    subtract, drop anyone who reaches zero. At most `n - 1` transfers for `n`
    participants. Ties break on `(-amount, name or "")`, a total order, so the
    same input always produces the same suggestion.
    """
    remaining = {name: amount for name, amount in positions.items() if amount != 0}

    def key(name: str | None) -> tuple[Decimal, str]:
        return (-remaining[name], name or "")

    transfers: list[tuple[str | None, str | None, Decimal]] = []
    while remaining:
        payer = min(remaining, key=key)
        receiver = max(remaining, key=key)
        quantity = min(remaining[payer], -remaining[receiver])
        transfers.append((payer, receiver, quantity))
        remaining[payer] -= quantity
        remaining[receiver] += quantity
        if remaining[payer] == 0:
            del remaining[payer]
        if remaining[receiver] == 0:
            del remaining[receiver]
    return transfers


class SettleUp(UnitOfWork[list[SuggestedTransfer], SettleUpError]):
    """The minimum set of settling transfers that zeroes out every person
    balance — globally, or restricted to one group's participants (design
    §8, §2.3). Nets once per unit (§8.2): euros and shares are never
    combined into one suggestion.

    A pure read: resolves current balances and returns values, writing
    nothing — since issue 011 made `OperationGroup` creation lazy, this
    leaves no group behind (§8.2's third criterion).
    """

    def execute(self, group_name: str | None = None) -> Result[list[SuggestedTransfer], SettleUpError]:
        def use_case(ctx: DbTransactionContext) -> Result[list[SuggestedTransfer], SettleUpError]:
            balances_res = _person_balances(ctx)
            if balances_res.is_err:
                return Result.err(balances_res.unwrap_err())
            balances = balances_res.unwrap()

            if group_name is not None:
                names_res = _group_participant_names(ctx, group_name)
                if names_res.is_err:
                    return Result.err(names_res.unwrap_err())
                names = names_res.unwrap()
                balances = [person for person in balances if person.person_name in names]

            # --group keeps each included person's full current balance and
            # recomputes "you" as the negation of just that subset's sum
            # (design §2.3, §8.2) — building positions from `balances` as
            # filtered above does exactly that, with no separate code path
            # for the unscoped case.
            positions_by_unit: dict[str, dict[str | None, Decimal]] = {}
            for person in balances:
                for unit_balance in person.balances:
                    positions_by_unit.setdefault(unit_balance.unit_identifier, {})[
                        person.person_name
                    ] = unit_balance.quantity
            for unit_positions in positions_by_unit.values():
                unit_positions[None] = -sum(unit_positions.values(), start=Decimal(0))

            transfers = [
                SuggestedTransfer(payer, payee, unit_identifier, quantity)
                for unit_identifier in sorted(positions_by_unit)
                for payer, payee, quantity in settle(positions_by_unit[unit_identifier])
            ]
            return Result.ok(transfers)

        return self._run(use_case)


def _group_participant_names(
    ctx: DbTransactionContext, group_name: str
) -> Result[set[str], SettleUpError]:
    """The people appearing in a group's current splits (design §8.2) — the
    same current-adjusting-entry filter `WhoOwesWhatByGroup` applies, since
    an undone split's group tag is stale rather than a live participation.
    """
    group_res = get_split_group_by_name_service(ctx, group_name)
    if group_res.is_err:
        return Result.err(group_res.unwrap_err())

    splits_res = splits_in_group_service(ctx, group_res.unwrap().id)
    if splits_res.is_err:
        return Result.err(splits_res.unwrap_err())

    people_res = get_account_by_name_service(ctx, PEOPLE_ROOT)
    if people_res.is_err:
        return Result.err(people_res.unwrap_err())
    people_ids_res = descendant_account_ids_service(ctx, people_res.unwrap().id)
    if people_ids_res.is_err:
        return Result.err(people_ids_res.unwrap_err())
    people_ids = set(people_ids_res.unwrap())

    names: set[str] = set()
    for split in splits_res.unwrap():
        if split.adjusting_entry_id is None:
            continue
        for line in split.adjusting_entry.lines:
            if line.account_id in people_ids:
                names.add(line.account.name)
    return Result.ok(names)
