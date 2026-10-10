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
from kohle.domain.models import AccountType, OperationGroup, UnitKind
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
    SettleUp,
    SplitImportedEntry,
    SuggestedTransfer,
    UnsplitEntry,
    WhoOwesWhat,
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


def test_who_owes_what(session: Session, people_root) -> None:
    ctx = DbTransactionContext(session)
    checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap().id
    eating_out = add_account_service(ctx, "Eating out", AccountType.expense).unwrap().id
    alice = add_account_service(ctx, "Alice", AccountType.asset, None, people_root.id).unwrap().id
    add_account_service(ctx, "Bob", AccountType.asset, None, people_root.id)
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap().id
    entry_id = _imported_dinner(ctx, checking, eating_out, eur)
    session.commit()

    SplitImportedEntry(session).execute(entry_id, Decimal(32), [PersonShare("Alice", Decimal(48))])
    # Alice settles in full: her account's lines cancel to a zero balance.
    ctx2 = DbTransactionContext(session)
    add_journal_entry_service(
        ctx2, date(2026, 3, 6), "settle-alice", "Alice pays back",
        [
            LineSpec(alice, eur, Decimal(48), Decimal(1), is_debit=False),
            LineSpec(checking, eur, Decimal(48), Decimal(1), is_debit=True),
        ],
    )
    session.commit()

    result = WhoOwesWhat(session).execute()
    assert result.is_ok
    people = {p.person_name: p for p in result.unwrap()}

    assert len(people["Alice"].balances) == 1
    assert people["Alice"].balances[0].unit_identifier == "EUR"
    assert people["Alice"].balances[0].quantity == Decimal(0)
    # Bob was never split against: absence, not a zero UnitBalance.
    assert people["Bob"].balances == []


def test_settle_up_use_case(session: Session, people_root) -> None:
    ctx = DbTransactionContext(session)
    checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap().id
    eating_out = add_account_service(ctx, "Eating out", AccountType.expense).unwrap().id
    alice = add_account_service(ctx, "Alice", AccountType.asset, None, people_root.id).unwrap().id
    add_account_service(ctx, "Bob", AccountType.asset, None, people_root.id)
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap().id
    dinner_id = _imported_dinner(ctx, checking, eating_out, eur)

    grocery_lines = [
        LineSpec(eating_out, eur, Decimal(60), Decimal(1), is_debit=True),
        LineSpec(checking, eur, Decimal(60), Decimal(1), is_debit=False),
    ]
    grocery_id = add_journal_entry_service(
        ctx, date(2026, 3, 2), "ref-groceries", "Groceries with Bob", grocery_lines
    ).unwrap().id
    add_classification_service(
        ctx, journal_entry_id=grocery_id, proposed_account_id=eating_out,
        matched_rule_id=None, final_account_id=eating_out,
    )
    AddSplitGroup(session).execute("Italy trip")
    session.commit()

    SplitImportedEntry(session).execute(
        dinner_id, Decimal(32), [PersonShare("Alice", Decimal(48))], "Italy trip"
    )
    SplitImportedEntry(session).execute(grocery_id, Decimal(40), [PersonShare("Bob", Decimal(20))])

    # Alice pays back part of what she owes: settle-up must use her live
    # balance (28), not the 48 she was originally split for.
    ctx2 = DbTransactionContext(session)
    add_journal_entry_service(
        ctx2, date(2026, 3, 6), "settle-alice-partial", "Alice pays back some",
        [
            LineSpec(alice, eur, Decimal(20), Decimal(1), is_debit=False),
            LineSpec(checking, eur, Decimal(20), Decimal(1), is_debit=True),
        ],
    )
    session.commit()

    groups_before = session.query(OperationGroup).count()

    global_result = SettleUp(session).execute()
    assert global_result.is_ok
    global_transfers = {
        (t.payer, t.payee, t.unit_identifier, t.quantity) for t in global_result.unwrap()
    }
    assert global_transfers == {
        ("Alice", None, "EUR", Decimal(28)),
        ("Bob", None, "EUR", Decimal(20)),
    }

    # Bob was never split under "Italy trip": scoping to the group excludes
    # him and recomputes "you" as the negation of just Alice's balance
    # (design §2.3, §8.2).
    scoped_result = SettleUp(session).execute("Italy trip")
    assert scoped_result.is_ok
    assert scoped_result.unwrap() == [SuggestedTransfer("Alice", None, "EUR", Decimal(28))]

    unknown_result = SettleUp(session).execute("Spain trip")
    assert unknown_result.is_err
    assert isinstance(unknown_result.unwrap_err(), SplitGroupNotFound)

    # A pure read: no OperationGroup left behind by either call.
    assert session.query(OperationGroup).count() == groups_before
