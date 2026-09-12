"""Layer 3 — the spec's primary acceptance scenario, end to end.

The worked scenario from dev/specs/expense-classification.md, in the shape of
test_cash_envelope_scenario.py: rules classify most of a statement, one line
falls through, it is found and corrected, and the ledger reflects all of it.

If this passes, issues 013 through 017 are done.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kohle.domain.models import AccountType, Operation, OperationGroup
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.classification import ListUnclassified, Reclassify
from kohle.use_cases.journal import ImportStatement, QueryAccountBalance
from kohle.use_cases.rules import AddRule


def test_classification_scenario(session: Session, statement_df, statement_row) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    AddAccount(session).execute("Groceries", AccountType.expense)
    AddAccount(session).execute("Books", AccountType.expense)

    # Step 1: a couple of rules against leaf expense accounts.
    assert AddRule(session).execute("REWE", "Groceries").is_ok
    assert AddRule(session).execute("AMZN", "Books").is_ok

    groups_before_import = session.scalar(select(func.count()).select_from(OperationGroup))

    # Step 2: a statement with counterparty data, one row matching no rule.
    df = statement_df([
        statement_row(date(2026, 3, 1), -42.0, "REWE SAGT DANKE", "REWE Markt GmbH", "DE89370400440532013000"),
        statement_row(date(2026, 3, 3), -18.0, "AMZN MKTP DE", "Amazon EU", "DE11500105170648489890"),
        statement_row(date(2026, 3, 5), -9.5, "Ticket Nr. 4471", "S-Bahn Berlin", None),
    ])

    # Step 3: matched rows land on their target accounts, the unmatched one
    # falls through to the unclassified bucket.
    assert ImportStatement(session).execute("Checking", df).unwrap() == 3

    groceries_balance = QueryAccountBalance(session).execute("Groceries").unwrap()
    assert any(b.quantity == Decimal("42.0") for b in groceries_balance)
    books_balance = QueryAccountBalance(session).execute("Books").unwrap()
    assert any(b.quantity == Decimal("18.0") for b in books_balance)
    unclassified_expense_balance = QueryAccountBalance(session).execute("Unclassified Expense").unwrap()
    assert any(b.quantity == Decimal("9.5") for b in unclassified_expense_balance)

    # The whole import is one operation group.
    groups_after_import = session.scalar(select(func.count()).select_from(OperationGroup))
    assert groups_after_import == groups_before_import + 1

    # Step 4: list-unclassified shows exactly the fallen-through line, with
    # enough on it to write a rule from.
    unclassified = ListUnclassified(session).execute().unwrap()
    assert len(unclassified) == 1
    fallen_through = unclassified[0]
    assert fallen_through.description == "Ticket Nr. 4471"
    assert fallen_through.counterparty_name == "S-Bahn Berlin"
    assert fallen_through.amount == Decimal("9.5")
    assert fallen_through.account_name == "Unclassified Expense"

    AddAccount(session).execute("Transport", AccountType.expense)

    # Step 5: reclassify it onto a leaf expense account, using the id
    # list-unclassified just printed.
    reclassify_result = Reclassify(session).execute(fallen_through.entry_id, "Transport")
    assert reclassify_result.is_ok

    # Step 6: balance reflects the correction on both accounts, and
    # list-unclassified is now empty — with no change to its query.
    unclassified_expense_after = QueryAccountBalance(session).execute("Unclassified Expense").unwrap()
    assert unclassified_expense_after == [] or all(b.quantity == 0 for b in unclassified_expense_after)
    transport_balance = QueryAccountBalance(session).execute("Transport").unwrap()
    assert any(b.quantity == Decimal("9.5") for b in transport_balance)
    assert ListUnclassified(session).execute().unwrap() == []

    # Step 7: the reclassify is its own operation group, separate from import.
    groups_after_reclassify = session.scalars(
        select(OperationGroup.id).order_by(OperationGroup.id)
    ).all()
    assert len(groups_after_reclassify) == groups_after_import + 2  # AddAccount("Transport") + Reclassify
    reclassify_ops = session.scalars(
        select(Operation).where(Operation.group_id == groups_after_reclassify[-1])
    ).all()
    assert {op.entity_type for op in reclassify_ops} >= {"journal_entries", "classifications"}
