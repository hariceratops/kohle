"""Layer 3 — use-case tests against the `session` fixture.

`SplitImportedEntry`, `UnsplitEntry`, `AddSplitGroup`, `WhoOwesWhat`,
`SettleUp` (issues 019, 020, 021, 022, 023) — the error paths in particular.
dev/design/expense-splitting.md §4.5 lists the conditions each must surface
as a clear error, not a traceback.

Requires the `people_root` fixture (conftest.py) — the migration-seeded
`People` account does not exist under `base.metadata.create_all` (design
§3.2), and every one of these use cases resolves it strictly.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 019")
def test_split_imported_entry() -> None:
    # TODO(019) — one test per site:
    #   - splitting a hand-entered `record` line -> NoClassificationForEntry
    #     (only imported lines have a classification, design §4.2)
    #   - an unknown person account -> AccountNotFoundError
    #   - a named account outside the People branch -> NotAPersonAccount
    #   - shares not summing to the line's quantity -> SplitDoesNotSumToLine
    #   - an unknown --group name -> SplitGroupNotFound
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 020")
def test_unsplit_entry() -> None:
    # TODO(020) — an entry with no splits row, and one already undone (its
    #   splits row has adjusting_entry_id IS NULL) -> both NoSplitForEntry
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 021")
def test_add_split_group() -> None:
    # TODO(021) — EmptySplitGroupName on a blank/whitespace-only name;
    #   DuplicateSplitGroup on a repeated name
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 022")
def test_who_owes_what() -> None:
    # TODO(022) — every person account is listed, including one with no
    #   lines (empty balances, renders as absence rather than zero); a
    #   settled person (lines cancel) has a UnitBalance with quantity 0
    #   (design §7.1)
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 023")
def test_settle_up_use_case() -> None:
    # TODO(023) — --group restricts the participant set to that group's
    #   people while still netting their full current balances, not the
    #   group's allocation total (design §2.3); nothing is stored, no
    #   OperationGroup is left behind
    raise NotImplementedError
