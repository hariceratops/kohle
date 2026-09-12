"""Layer 2 — service tests against the `session` fixture.

`split_services.py` (issues 019, 021): the `splits` and `split_groups` CRUD
that the use-case layer builds on. dev/design/expense-splitting.md §4.4 and
§6 — the unique constraint on `journal_entry_id` and on `split_groups.name`
are what these tests exist to pin down.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 019")
def test_split_record() -> None:
    # TODO(019) — one test per site:
    #   - a split is created linking journal_entry_id to its adjusting_entry_id
    #   - UniqueConstraint(journal_entry_id): a second split for the same
    #     entry is an update, not a second row (design §4.4)
    #   - split_by_entry_service returns NoSplitForEntry when no row exists
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 021")
def test_split_group_record() -> None:
    # TODO(021) — one test per site:
    #   - add_split_group_service creates a group with a UNIQUE name
    #   - a duplicate name maps to DuplicateSplitGroup, not the raw
    #     UNIQUE-constraint violation
    #   - splits_in_group_service returns a group's member splits, eager
    #     loading the adjusting entry and its lines (design §6)
    raise NotImplementedError
