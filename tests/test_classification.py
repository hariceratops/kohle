"""Layer 3 — use-case tests against the `session` fixture.

`ListUnclassified` (issue 016).

The predicate is final_account_id IN (bucket ids), not matched_rule_id IS
NULL — dev/design/expense-classification.md §6.1 explains why the spec's "or
equivalently" is wrong, and issue 016's own acceptance criteria only hold
under the second predicate.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from kohle.domain.models import Account, AccountType, UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.account_services import add_account_service
from kohle.services.classification_services import add_classification_service
from kohle.services.journal_services import LineSpec, add_journal_entry_service
from kohle.services.rule_services import add_rule_service
from kohle.services.unit_services import add_unit_service
from kohle.use_cases.classification import ListUnclassified
from kohle.use_cases.journal import UNCLASSIFIED_EXPENSE, UNCLASSIFIED_INCOME


def test_empty_ledger_reports_no_error(session: Session) -> None:
    """Nothing imported yet means neither bucket exists — resolved with the
    strict lookup, never _get_or_create_account, so a read-only command
    cannot write two accounts and leave an operation group behind."""

    result = ListUnclassified(session).execute()

    assert result.is_ok
    assert result.unwrap() == []
    assert session.query(Account).count() == 0


def test_lists_the_fallen_through_line_and_omits_the_matched_one(session: Session) -> None:
    ctx = DbTransactionContext(session)
    checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap().id
    groceries = add_account_service(ctx, "Groceries", AccountType.expense).unwrap().id
    bucket = add_account_service(ctx, UNCLASSIFIED_EXPENSE, AccountType.expense).unwrap().id
    add_account_service(ctx, UNCLASSIFIED_INCOME, AccountType.income)
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap().id
    rule = add_rule_service(ctx, "REWE", groceries, 100).unwrap().id

    def post(reference: str, counterpart_id: int, description: str) -> int:
        value = Decimal(80)
        lines = [
            LineSpec(counterpart_id, eur, value, Decimal(1), is_debit=True),
            LineSpec(checking, eur, value, Decimal(1), is_debit=False),
        ]
        return add_journal_entry_service(
            ctx, date(2026, 3, 1), reference, description, lines
        ).unwrap().id

    matched_entry_id = post("ref-1", groceries, "REWE SAGT DANKE")
    fallen_through_entry_id = post("ref-2", bucket, "Unknown shop")

    add_classification_service(
        ctx, journal_entry_id=matched_entry_id, proposed_account_id=groceries,
        matched_rule_id=rule, final_account_id=groceries,
    )
    add_classification_service(
        ctx, journal_entry_id=fallen_through_entry_id, proposed_account_id=bucket,
        matched_rule_id=None, final_account_id=bucket,
    )
    session.commit()

    result = ListUnclassified(session).execute()

    assert result.is_ok
    lines = result.unwrap()
    assert len(lines) == 1
    line = lines[0]
    assert line.entry_id == fallen_through_entry_id
    assert line.description == "Unknown shop"
    assert line.account_name == UNCLASSIFIED_EXPENSE
    assert line.amount == Decimal(80)
