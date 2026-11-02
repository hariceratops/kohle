"""Layer 3 — use-case tests against the `session` fixture.

`AddRule`, `ListRules` and `RemoveRule` (issue 014).

The pattern is compiled when the rule is created, not when an import later
runs it. That is issue 014's acceptance criterion and the whole reason
dev/design/expense-classification.md §2.1 chose regexes over substrings: a
malformed pattern has to be rejectable at creation, and every string is a
valid substring pattern.
"""

from sqlalchemy.orm import Session

from kohle.domain.domain_errors import (
    AccountNotFoundError,
    EmptyRulePattern,
    InvalidRulePattern,
    PostingToNonLeafAccount,
    RuleNotFoundError,
)
from kohle.domain.models import AccountType, Operation, Rule
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.conditions import When
from kohle.use_cases.operations import ListOperations
from kohle.use_cases.rules import RULE_PRIORITY_STEP, AddRule, ListRules, RemoveRule


def test_add_rule_success(session: Session) -> None:
    AddAccount(session).execute("Groceries", AccountType.expense)

    result = AddRule(session).execute("REWE", "Groceries")
    assert result.is_ok
    rule = result.unwrap()
    assert rule.condition == '{ any_field = "REWE" }'
    assert rule.priority == RULE_PRIORITY_STEP

    operations = ListOperations(session).execute().unwrap()
    assert operations[0] == Operation(
        group_id=2, entity_type="rules", entity_id=rule.id, action="create"
    )


def test_add_rule_rejects_a_malformed_pattern_at_creation(session: Session) -> None:
    AddAccount(session).execute("Groceries", AccountType.expense)

    result = AddRule(session).execute("REWE[", "Groceries")
    assert result.is_err
    err = result.unwrap_err()
    assert isinstance(err, InvalidRulePattern)
    # The position is what makes the message actionable, and it comes from
    # re.error rather than from anything written here.
    assert "position 4" in str(err)

    assert ListRules(session).execute().unwrap() == []


def test_add_rule_rejects_an_empty_pattern(session: Session) -> None:
    AddAccount(session).execute("Groceries", AccountType.expense)

    result = AddRule(session).execute("   ", "Groceries")
    assert result.is_err
    assert isinstance(result.unwrap_err(), EmptyRulePattern)


def test_add_rule_rejects_an_unknown_account(session: Session) -> None:
    result = AddRule(session).execute("REWE", "Grocerys")
    assert result.is_err
    assert isinstance(result.unwrap_err(), AccountNotFoundError)


def test_add_rule_rejects_a_non_leaf_account(session: Session) -> None:
    """A rule aimed at a parent could only ever produce entries validate_lines
    refuses, so the refusal happens here rather than at the import."""
    AddAccount(session).execute("Living", AccountType.expense)
    AddAccount(session).execute("Groceries", AccountType.expense, None, "Living")

    result = AddRule(session).execute("REWE", "Living")
    assert result.is_err
    assert isinstance(result.unwrap_err(), PostingToNonLeafAccount)


def test_add_rule_appends_after_the_last_live_rule(session: Session) -> None:
    AddAccount(session).execute("Groceries", AccountType.expense)

    first = AddRule(session).execute("REWE", "Groceries").unwrap()
    second = AddRule(session).execute("ALDI", "Groceries").unwrap()
    third = AddRule(session).execute("LIDL", "Groceries").unwrap()

    assert [first.priority, second.priority, third.priority] == [100, 200, 300]


def test_add_rule_appends_after_the_last_live_rule_not_a_retired_one(session: Session) -> None:
    AddAccount(session).execute("Groceries", AccountType.expense)
    AddRule(session).execute("REWE", "Groceries")
    last = AddRule(session).execute("ALDI", "Groceries").unwrap()
    RemoveRule(session).execute(last.id)

    assert AddRule(session).execute("LIDL", "Groceries").unwrap().priority == 200


def test_list_rules_renders_them_in_evaluation_order(session: Session) -> None:
    AddAccount(session).execute("Groceries", AccountType.expense)
    AddRule(session).execute(".", "Groceries")
    AddRule(session).execute("REWE", "Groceries")

    rules = ListRules(session).execute().unwrap()
    assert [rule.when for rule in rules] == [When(any_field="."), When(any_field="REWE")]
    # The account name is read after the session closes, so the listing has to
    # arrive with it already loaded.
    assert [rule.account_name for rule in rules] == ["Groceries", "Groceries"]


def test_remove_rule_retires_a_rule_that_has_already_fired(session: Session) -> None:
    AddAccount(session).execute("Groceries", AccountType.expense)
    rule = AddRule(session).execute("REWE", "Groceries").unwrap()

    result = RemoveRule(session).execute(rule.id)
    assert result.is_ok

    assert ListRules(session).execute().unwrap() == []
    # Retired, not gone: a classification that named this rule keeps a condition
    # to explain itself with.
    assert session.query(Rule).filter(Rule.id == rule.id).one().condition == '{ any_field = "REWE" }'

    # A soft delete is recorded as a delete, not as an update of deleted_at:
    # the audit trail exists to say what happened.
    operations = ListOperations(session).execute().unwrap()
    assert operations[0] == Operation(
        group_id=3, entity_type="rules", entity_id=rule.id, action="delete"
    )


def test_remove_rule_on_an_unknown_id(session: Session) -> None:
    result = RemoveRule(session).execute(42)
    assert result.is_err
    assert isinstance(result.unwrap_err(), RuleNotFoundError)
