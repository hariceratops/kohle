"""Layer 3 — use-case tests against the `session` fixture.

`SplitImportedEntry`, `UnsplitEntry`, `AddSplitGroup`, `WhoOwesWhat`,
`SettleUp` (issues 019, 020, 021, 022, 023) — the error paths in particular.
dev/design/expense-splitting.md §4.5 lists the conditions each must surface
as a clear error, not a traceback.

Requires the `people_root` fixture (conftest.py) — the migration-seeded
`People` account does not exist under `base.metadata.create_all` (design
§3.2), and every one of these use cases resolves it strictly.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from kohle.domain.domain_errors import (
    AccountNotFoundError,
    DuplicateSplitGroup,
    EmptySplitGroupName,
    NoClassificationForEntry,
    NoSplitForEntry,
    NotAPersonAccount,
    SplitDoesNotSumToLine,
    SplitGroupNotFound,
)
from kohle.domain.models import AccountType, UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.account_services import add_account_service
from kohle.services.classification_services import add_classification_service
from kohle.services.journal_services import LineSpec, add_journal_entry_service
from kohle.services.split_services import split_by_entry_service
from kohle.services.unit_services import add_unit_service
from kohle.use_cases.journal import RecordSimpleEntry
from kohle.use_cases.splitting import (
    AddSplitGroup,
    PersonShare,
    SplitImportedEntry,
    UnsplitEntry,
)


def _imported_dinner(ctx: DbTransactionContext, checking_id: int, eating_out_id: int, eur_id: int) -> int:
    value = Decimal(80)
    lines = [
        LineSpec(eating_out_id, eur_id, value, Decimal(1), is_debit=True),
        LineSpec(checking_id, eur_id, value, Decimal(1), is_debit=False),
    ]
    entry_id = add_journal_entry_service(
        ctx, date(2026, 3, 1), "ref-dinner", "Dinner with Alice", lines
    ).unwrap().id
    add_classification_service(
        ctx,
        journal_entry_id=entry_id,
        proposed_account_id=eating_out_id,
        matched_rule_id=None,
        final_account_id=eating_out_id,
    ).unwrap()
    return entry_id


def test_split_imported_entry_a_hand_entered_line_has_no_classification(
    session: Session, people_root
) -> None:
    ctx = DbTransactionContext(session)
    add_account_service(ctx, "Checking", AccountType.asset, "DE1")
    add_account_service(ctx, "Eating out", AccountType.expense)
    add_account_service(ctx, "Alice", AccountType.asset, None, people_root.id)
    session.commit()

    recorded = RecordSimpleEntry(session).execute(
        date(2026, 3, 1), "Manual entry", Decimal(80), "Checking", "Eating out"
    )
    assert recorded.is_ok

    # record/record-split entries have no classification row — only imported
    # lines can be split (design §4.2).
    result = SplitImportedEntry(session).execute(
        recorded.unwrap().id, Decimal(32), [PersonShare("Alice", Decimal(48))]
    )
    assert result.is_err
    assert isinstance(result.unwrap_err(), NoClassificationForEntry)


def test_split_imported_entry_an_unknown_person_account(session: Session, people_root) -> None:
    ctx = DbTransactionContext(session)
    checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap().id
    eating_out = add_account_service(ctx, "Eating out", AccountType.expense).unwrap().id
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap().id
    entry_id = _imported_dinner(ctx, checking, eating_out, eur)
    session.commit()

    result = SplitImportedEntry(session).execute(entry_id, Decimal(32), [PersonShare("Bob", Decimal(48))])
    assert result.is_err
    assert isinstance(result.unwrap_err(), AccountNotFoundError)


def test_split_imported_entry_an_account_outside_the_people_branch(session: Session, people_root) -> None:
    ctx = DbTransactionContext(session)
    checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap().id
    eating_out = add_account_service(ctx, "Eating out", AccountType.expense).unwrap().id
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap().id
    entry_id = _imported_dinner(ctx, checking, eating_out, eur)
    session.commit()

    result = SplitImportedEntry(session).execute(entry_id, Decimal(32), [PersonShare("Checking", Decimal(48))])
    assert result.is_err
    assert isinstance(result.unwrap_err(), NotAPersonAccount)


def test_split_imported_entry_shares_not_summing_to_the_line(session: Session, people_root) -> None:
    ctx = DbTransactionContext(session)
    checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap().id
    eating_out = add_account_service(ctx, "Eating out", AccountType.expense).unwrap().id
    add_account_service(ctx, "Alice", AccountType.asset, None, people_root.id)
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap().id
    entry_id = _imported_dinner(ctx, checking, eating_out, eur)
    session.commit()

    result = SplitImportedEntry(session).execute(entry_id, Decimal(32), [PersonShare("Alice", Decimal(40))])
    assert result.is_err
    err = result.unwrap_err()
    assert isinstance(err, SplitDoesNotSumToLine)
    assert err.line_quantity == Decimal(80)
    assert err.given == Decimal(72)


def test_unsplit_entry_with_no_splits_row(session: Session, people_root) -> None:
    ctx = DbTransactionContext(session)
    checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap().id
    eating_out = add_account_service(ctx, "Eating out", AccountType.expense).unwrap().id
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap().id
    entry_id = _imported_dinner(ctx, checking, eating_out, eur)
    session.commit()

    result = UnsplitEntry(session).execute(entry_id)
    assert result.is_err
    assert isinstance(result.unwrap_err(), NoSplitForEntry)


def test_unsplit_entry_already_undone(session: Session, people_root) -> None:
    ctx = DbTransactionContext(session)
    checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap().id
    eating_out = add_account_service(ctx, "Eating out", AccountType.expense).unwrap().id
    add_account_service(ctx, "Alice", AccountType.asset, None, people_root.id)
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap().id
    entry_id = _imported_dinner(ctx, checking, eating_out, eur)
    session.commit()

    split = SplitImportedEntry(session).execute(entry_id, Decimal(32), [PersonShare("Alice", Decimal(48))])
    assert split.is_ok

    undone = UnsplitEntry(session).execute(entry_id)
    assert undone.is_ok

    # The splits row has adjusting_entry_id IS NULL now — undoing it a
    # second time is the same NoSplitForEntry an unknown reference gets
    # (design §5.1).
    result = UnsplitEntry(session).execute(entry_id)
    assert result.is_err
    assert isinstance(result.unwrap_err(), NoSplitForEntry)


def test_add_split_group(session: Session) -> None:
    result = AddSplitGroup(session).execute("  ")
    assert result.is_err
    assert isinstance(result.unwrap_err(), EmptySplitGroupName)

    created = AddSplitGroup(session).execute("Italy trip")
    assert created.is_ok
    assert created.unwrap().name == "Italy trip"

    duplicate = AddSplitGroup(session).execute("Italy trip")
    assert duplicate.is_err
    duplicate_err = duplicate.unwrap_err()
    assert isinstance(duplicate_err, DuplicateSplitGroup)
    assert duplicate_err.name == "Italy trip"


def test_split_imported_entry_with_an_unknown_group(session: Session, people_root) -> None:
    ctx = DbTransactionContext(session)
    checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap().id
    eating_out = add_account_service(ctx, "Eating out", AccountType.expense).unwrap().id
    add_account_service(ctx, "Alice", AccountType.asset, None, people_root.id)
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap().id
    entry_id = _imported_dinner(ctx, checking, eating_out, eur)
    session.commit()

    result = SplitImportedEntry(session).execute(
        entry_id, Decimal(32), [PersonShare("Alice", Decimal(48))], "Itlay trip"
    )
    assert result.is_err
    err = result.unwrap_err()
    assert isinstance(err, SplitGroupNotFound)
    assert err.name == "Itlay trip"


def test_split_imported_entry_group_is_authoritative_on_every_run(session: Session, people_root) -> None:
    ctx = DbTransactionContext(session)
    checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap().id
    eating_out = add_account_service(ctx, "Eating out", AccountType.expense).unwrap().id
    add_account_service(ctx, "Alice", AccountType.asset, None, people_root.id)
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap().id
    entry_id = _imported_dinner(ctx, checking, eating_out, eur)
    italy = AddSplitGroup(session).execute("Italy trip").unwrap()
    spain = AddSplitGroup(session).execute("Spain trip").unwrap()
    session.commit()

    split = SplitImportedEntry(session).execute(
        entry_id, Decimal(32), [PersonShare("Alice", Decimal(48))], "Italy trip"
    )
    assert split.is_ok
    row = split_by_entry_service(DbTransactionContext(session), entry_id).unwrap()
    assert row.group_id == italy.id

    # Re-splitting with a different --group moves it.
    split = SplitImportedEntry(session).execute(
        entry_id, Decimal(40), [PersonShare("Alice", Decimal(40))], "Spain trip"
    )
    assert split.is_ok
    row = split_by_entry_service(DbTransactionContext(session), entry_id).unwrap()
    assert row.group_id == spain.id

    # Re-splitting without --group clears it.
    split = SplitImportedEntry(session).execute(
        entry_id, Decimal(40), [PersonShare("Alice", Decimal(40))]
    )
    assert split.is_ok
    row = split_by_entry_service(DbTransactionContext(session), entry_id).unwrap()
    assert row.group_id is None


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
