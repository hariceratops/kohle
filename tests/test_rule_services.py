"""Layer 2 — service tests against the `session` fixture.

Rule persistence (issue 014). The ordering `list_rules_service` returns is
load-bearing: `compile_rules` preserves it rather than re-sorting, so
evaluation order is a property of this query.

`remove_rule_service` is a soft delete, and not stylistically —
dev/design/expense-classification.md §4.3 records why a hard delete is
unavailable and why ON DELETE SET NULL would be worse than either.
"""

from sqlalchemy.orm import Session

from kohle.domain.domain_errors import RuleNotFoundError
from kohle.domain.models import Account, AccountType, Rule
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.account_services import add_account_service
from kohle.services.rule_services import (
    add_rule_service,
    list_rules_service,
    remove_rule_service,
)


def _account(ctx: DbTransactionContext, name: str) -> Account:
    return add_account_service(ctx, name, AccountType.expense).unwrap()


def test_list_rules_orders_by_priority_then_id(session: Session) -> None:
    ctx = DbTransactionContext(session)
    groceries = _account(ctx, "Groceries")

    late = add_rule_service(ctx, "LIDL", groceries.id, 200).unwrap()
    first_of_the_tie = add_rule_service(ctx, "REWE", groceries.id, 100).unwrap()
    second_of_the_tie = add_rule_service(ctx, "ALDI", groceries.id, 100).unwrap()

    result = list_rules_service(ctx)
    assert result.is_ok
    # The tie resolves on id, so the two priority-100 rules keep the order they
    # were created in rather than whatever the database happens to return.
    assert [rule.id for rule in result.unwrap()] == [
        first_of_the_tie.id,
        second_of_the_tie.id,
        late.id,
    ]


def test_retired_rule_is_absent_from_the_listing(session: Session) -> None:
    ctx = DbTransactionContext(session)
    groceries = _account(ctx, "Groceries")
    retired = add_rule_service(ctx, "REWE", groceries.id, 100).unwrap()
    kept = add_rule_service(ctx, "ALDI", groceries.id, 100).unwrap()

    assert remove_rule_service(ctx, retired.id).is_ok

    assert [rule.id for rule in list_rules_service(ctx).unwrap()] == [kept.id]


def test_remove_retires_the_row_rather_than_deleting_it(session: Session) -> None:
    ctx = DbTransactionContext(session)
    groceries = _account(ctx, "Groceries")
    rule = add_rule_service(ctx, "REWE", groceries.id, 100).unwrap()

    result = remove_rule_service(ctx, rule.id)
    assert result.is_ok
    assert result.unwrap().deleted_at is not None

    # The pattern text is what keeps a past classification interpretable, so
    # the row has to survive the removal.
    stored = session.query(Rule).filter(Rule.id == rule.id).one()
    assert stored.pattern == "REWE"
    assert stored.deleted_at is not None


def test_removing_an_already_retired_rule_reports_it_missing(session: Session) -> None:
    ctx = DbTransactionContext(session)
    groceries = _account(ctx, "Groceries")
    rule = add_rule_service(ctx, "REWE", groceries.id, 100).unwrap()
    assert remove_rule_service(ctx, rule.id).is_ok

    result = remove_rule_service(ctx, rule.id)
    assert result.is_err
    assert isinstance(result.unwrap_err(), RuleNotFoundError)
