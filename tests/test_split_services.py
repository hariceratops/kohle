"""Layer 2 — service tests against the `session` fixture.

`split_services.py` (issues 019, 021): the `splits` and `split_groups` CRUD
that the use-case layer builds on. dev/design/expense-splitting.md §4.4 and
§6 — the unique constraint on `journal_entry_id` and on `split_groups.name`
are what these tests exist to pin down.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from kohle.domain.domain_errors import DuplicateSplitGroup, NoSplitForEntry
from kohle.domain.models import AccountType, Split, UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.account_services import add_account_service
from kohle.services.journal_services import LineSpec, add_journal_entry_service
from kohle.services.split_services import (
    add_split_group_service,
    set_split_adjusting_entry_service,
    set_split_group_service,
    split_by_entry_service,
    splits_in_group_service,
)
from kohle.services.unit_services import add_unit_service


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


def test_split_group_record(session: Session) -> None:
    ctx = DbTransactionContext(session)

    created = add_split_group_service(ctx, "Italy trip")
    assert created.is_ok
    group = created.unwrap()
    assert group.name == "Italy trip"

    checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap().id
    eating_out = add_account_service(ctx, "Eating out", AccountType.expense).unwrap().id
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap().id
    value = Decimal(80)
    entry_id = add_journal_entry_service(
        ctx, date(2026, 3, 1), "ref-dinner", "Dinner",
        [
            LineSpec(eating_out, eur, value, Decimal(1), is_debit=True),
            LineSpec(checking, eur, value, Decimal(1), is_debit=False),
        ],
    ).unwrap().id

    adjusting_entry_id = add_journal_entry_service(
        ctx, date(2026, 3, 1), "ref-dinner-split", "Split: Dinner",
        [
            LineSpec(eating_out, eur, value, Decimal(1), is_debit=False),
            LineSpec(eating_out, eur, Decimal(32), Decimal(1), is_debit=True),
        ],
    ).unwrap().id
    set_split_adjusting_entry_service(ctx, entry_id, adjusting_entry_id)
    set_split_group_service(ctx, entry_id, group.id)

    # splits_in_group_service returns the group's member splits, eager
    # loading the adjusting entry and its lines (design §6).
    found = splits_in_group_service(ctx, group.id)
    assert found.is_ok
    splits = found.unwrap()
    assert len(splits) == 1
    assert splits[0].journal_entry_id == entry_id
    assert splits[0].adjusting_entry.id == adjusting_entry_id
    assert len(splits[0].adjusting_entry.lines) == 2

    empty = splits_in_group_service(ctx, group.id + 1)
    assert empty.is_ok
    assert empty.unwrap() == []

    # A duplicate name maps to DuplicateSplitGroup, not the raw
    # UNIQUE-constraint violation. Left last: the failed insert rolls the
    # session's pending transaction back, unusable for further writes.
    duplicate = add_split_group_service(ctx, "Italy trip")
    assert duplicate.is_err
    assert isinstance(duplicate.unwrap_err(), DuplicateSplitGroup)
    assert duplicate.unwrap_err().name == "Italy trip"
