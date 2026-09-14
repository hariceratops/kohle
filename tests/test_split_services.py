"""Layer 2 — service tests against the `session` fixture.

`split_services.py` (issues 019, 021): the `splits` and `split_groups` CRUD
that the use-case layer builds on. dev/design/expense-splitting.md §4.4 and
§6 — the unique constraint on `journal_entry_id` and on `split_groups.name`
are what these tests exist to pin down.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from kohle.domain.domain_errors import NoSplitForEntry
from kohle.domain.models import Split
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.split_services import (
    set_split_adjusting_entry_service,
    split_by_entry_service,
)


def test_split_record(session: Session) -> None:
    ctx = DbTransactionContext(session)

    # No row yet: the not-found error, not emptiness or a raw None.
    missing = split_by_entry_service(ctx, 1)
    assert missing.is_err
    assert isinstance(missing.unwrap_err(), NoSplitForEntry)
    assert missing.unwrap_err().entry_id == 1

    # First call creates the row linking journal_entry_id to adjusting_entry_id.
    created = set_split_adjusting_entry_service(ctx, 1, 10)
    assert created.is_ok
    split = created.unwrap()
    assert split.journal_entry_id == 1
    assert split.adjusting_entry_id == 10

    found = split_by_entry_service(ctx, 1)
    assert found.is_ok
    assert found.unwrap().id == split.id

    # UniqueConstraint(journal_entry_id): a second split for the same entry
    # is an update, not a second row.
    updated = set_split_adjusting_entry_service(ctx, 1, 20)
    assert updated.is_ok
    assert updated.unwrap().id == split.id
    assert updated.unwrap().adjusting_entry_id == 20

    rows = session.scalars(select(Split).where(Split.journal_entry_id == 1)).all()
    assert len(rows) == 1


@pytest.mark.skip(reason="scaffold: issue 021")
def test_split_group_record() -> None:
    # TODO(021) — one test per site:
    #   - add_split_group_service creates a group with a UNIQUE name
    #   - a duplicate name maps to DuplicateSplitGroup, not the raw
    #     UNIQUE-constraint violation
    #   - splits_in_group_service returns a group's member splits, eager
    #     loading the adjusting entry and its lines (design §6)
    raise NotImplementedError
