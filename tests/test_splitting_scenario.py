"""Layer 3 — end-to-end scenario, in the shape of test_cash_envelope_scenario.py.

The spec's own worked example (dev/specs/expense-splitting.md): import a
line, split it retroactively between the user's own expense account and a
person account, undo it, edit it, and interact with `reclassify`. If this
passes, issues 019-021's core paths are done (018 is covered directly in
test_migration_downgrade.py and test_cli.py).

Requires the `people_root` fixture (conftest.py).
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 019")
def test_split_an_imported_line_scenario() -> None:
    # TODO(019) — the spec's acceptance test: import an 80 EUR dinner, split
    #   32 own / 48 Alice, assert Eating out holds 32 and People:Alice holds
    #   a 48 receivable, and the splits row links both entries back to the
    #   import.
    #
    # TODO(019) — an income line split leaves the person account NEGATIVE
    #   (the branch-free mirror of design §4.3 — the case that would be
    #   wrong if anyone introduced an expense/income branch later).
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 020")
def test_undo_and_edit_a_split_scenario() -> None:
    # TODO(020) — undo restores balances to exactly the pre-split state; the
    #   original entry is untouched; the splits row survives with
    #   adjusting_entry_id IS NULL (design §5.1).
    #
    # TODO(020) — editing 32/48 -> 40/40 replaces the allocation in one
    #   transaction (one OperationGroup); all four entries (import, split,
    #   reversal, re-split) remain readable (design §5.3).
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 019")
def test_reclassify_split_interaction_guards() -> None:
    # TODO(019) REGRESSION — split first, then reclassify: refused with
    #   EntryAlreadySplit, and balances are unchanged by the refusal (design
    #   §5.4). Without this guard the two features silently corrupt a
    #   balance.
    #
    # TODO(019) — reclassify first, then split: the shares come out of the
    #   corrected account (final_account_id), not the original bucket
    #   (design §4.2).
    raise NotImplementedError
