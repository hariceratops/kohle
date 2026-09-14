"""Layer 3 — end-to-end scenario, in the shape of test_cash_envelope_scenario.py.

The spec's own worked example (dev/specs/expense-splitting.md): import a
line, split it retroactively between the user's own expense account and a
person account, undo it, edit it, and interact with `reclassify`. If this
passes, issues 019-021's core paths are done (018 is covered directly in
test_migration_downgrade.py and test_cli.py).

Requires the `people_root` fixture (conftest.py).
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from kohle.domain.domain_errors import EntryAlreadySplit
from kohle.domain.models import AccountType
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.split_services import split_by_entry_service
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.classification import ListUnclassified, Reclassify
from kohle.use_cases.journal import ImportStatement, QueryAccountBalance
from kohle.use_cases.splitting import PersonShare, SplitImportedEntry


def test_split_an_imported_line_scenario(session: Session, people_root, statement_df, statement_row) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    AddAccount(session).execute("Eating out", AccountType.expense)
    AddAccount(session).execute("Alice", AccountType.asset, None, "People")

    df = statement_df([statement_row(date(2026, 3, 1), -80.0, "Dinner")])
    imported = ImportStatement(session).execute("Checking", df)
    assert imported.is_ok

    # Freshly imported, the line sits in the unclassified bucket; move it to
    # Eating out before splitting so the scenario matches the spec's example.
    unclassified = ListUnclassified(session).execute().unwrap()
    entry_id = unclassified[0].entry_id
    reclassified = Reclassify(session).execute(entry_id, "Eating out")
    assert reclassified.is_ok

    split = SplitImportedEntry(session).execute(
        entry_id, Decimal(32), [PersonShare("Alice", Decimal(48))]
    )
    assert split.is_ok

    eating_out_balance = QueryAccountBalance(session).execute("Eating out").unwrap()
    assert any(b.quantity == Decimal(32) for b in eating_out_balance)

    alice_balance = QueryAccountBalance(session).execute("Alice").unwrap()
    assert any(b.quantity == Decimal(48) for b in alice_balance)

    split_row = split_by_entry_service(DbTransactionContext(session), entry_id)
    assert split_row.is_ok
    assert split_row.unwrap().journal_entry_id == entry_id
    assert split_row.unwrap().adjusting_entry_id == split.unwrap().id


def test_splitting_an_income_line_leaves_the_person_account_negative(
    session: Session, people_root, statement_df, statement_row
) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    AddAccount(session).execute("Reimbursements", AccountType.income)
    AddAccount(session).execute("Alice", AccountType.asset, None, "People")

    df = statement_df([statement_row(date(2026, 3, 1), 80.0, "Shared refund")])
    imported = ImportStatement(session).execute("Checking", df)
    assert imported.is_ok

    unclassified = ListUnclassified(session).execute().unwrap()
    entry_id = unclassified[0].entry_id
    reclassified = Reclassify(session).execute(entry_id, "Reimbursements")
    assert reclassified.is_ok

    split = SplitImportedEntry(session).execute(
        entry_id, Decimal(32), [PersonShare("Alice", Decimal(48))]
    )
    assert split.is_ok

    # Reimbursements is credit-normal, so the fold reports its own share as
    # -32, not +32 — the same sign a plain income entry already gets
    # (design §9.2's "a credit-normal account accumulates credits, and the
    # fold subtracts them").
    reimbursements_balance = QueryAccountBalance(session).execute("Reimbursements").unwrap()
    assert any(b.quantity == Decimal(-32) for b in reimbursements_balance)

    # The person account goes negative too: you are holding money that is theirs.
    alice_balance = QueryAccountBalance(session).execute("Alice").unwrap()
    assert any(b.quantity == Decimal(-48) for b in alice_balance)


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


def test_reclassify_split_interaction_guards(
    session: Session, people_root, statement_df, statement_row
) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    AddAccount(session).execute("Eating out", AccountType.expense)
    AddAccount(session).execute("Restaurants", AccountType.expense)
    AddAccount(session).execute("Alice", AccountType.asset, None, "People")

    df = statement_df([statement_row(date(2026, 3, 1), -80.0, "Dinner")])
    imported = ImportStatement(session).execute("Checking", df)
    assert imported.is_ok

    unclassified = ListUnclassified(session).execute().unwrap()
    entry_id = unclassified[0].entry_id
    reclassified = Reclassify(session).execute(entry_id, "Eating out")
    assert reclassified.is_ok

    # Split first, then reclassify: refused, and balances are unchanged.
    split = SplitImportedEntry(session).execute(
        entry_id, Decimal(32), [PersonShare("Alice", Decimal(48))]
    )
    assert split.is_ok

    refused = Reclassify(session).execute(entry_id, "Restaurants")
    assert refused.is_err
    assert isinstance(refused.unwrap_err(), EntryAlreadySplit)

    eating_out_balance = QueryAccountBalance(session).execute("Eating out").unwrap()
    assert any(b.quantity == Decimal(32) for b in eating_out_balance)
    restaurants_balance = QueryAccountBalance(session).execute("Restaurants").unwrap()
    assert restaurants_balance == [] or all(b.quantity == 0 for b in restaurants_balance)

    # Reclassify first, then split: the shares come out of the corrected
    # account, not the original bucket (design §4.2).
    df2 = statement_df([statement_row(date(2026, 3, 2), -80.0, "Dinner two")])
    imported2 = ImportStatement(session).execute("Checking", df2)
    assert imported2.is_ok
    unclassified2 = ListUnclassified(session).execute().unwrap()
    entry_id2 = unclassified2[0].entry_id
    reclassified2 = Reclassify(session).execute(entry_id2, "Restaurants")
    assert reclassified2.is_ok

    split2 = SplitImportedEntry(session).execute(
        entry_id2, Decimal(32), [PersonShare("Alice", Decimal(48))]
    )
    assert split2.is_ok

    restaurants_balance2 = QueryAccountBalance(session).execute("Restaurants").unwrap()
    assert any(b.quantity == Decimal(32) for b in restaurants_balance2)
    bucket_balance = QueryAccountBalance(session).execute("Unclassified Expense").unwrap()
    assert bucket_balance == [] or all(b.quantity == 0 for b in bucket_balance)
