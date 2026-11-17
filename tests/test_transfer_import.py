"""Layer 2 — import-statement end to end for transfers (issues 126-128). Design §18.2-18.3."""

from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kohle.core.result import Result
from kohle.domain.models import (
    AccountType,
    Classification,
    ClassificationKind,
    JournalEntry,
    OperationGroup,
    Rule,
    RuleKind,
)
from kohle.use_cases import journal as journal_module
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.journal import ImportStatement
from kohle.use_cases.rules import ApplyRuleFile, PlanRuleFile, ShowRules

SAVINGS_IBAN = "DE44500105175407324931"
BUCKETS = ("Unclassified Expense", "Unclassified Income")


def _apply(session: Session, text: str) -> Result:
    plan = PlanRuleFile(session).execute(text)
    if plan.is_err:
        return plan
    return ApplyRuleFile(session).execute(text, plan.unwrap().base)


def _transfer_rule(account: str, iban: str = SAVINGS_IBAN) -> str:
    return f'[[rule]]\ntransfer = "{account}"\n[rule.when]\niban = "{iban}"\n'


def _ledger(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset)
    AddAccount(session).execute("Savings", AccountType.asset)
    AddAccount(session).execute("Groceries", AccountType.expense)


def _balances(session: Session) -> dict[str, int]:
    from kohle.domain.models import Account, JournalLine

    rows = session.execute(
        select(Account.name, func.sum(JournalLine.quantity * func.iif(JournalLine.is_debit, 1, -1)))
        .join(JournalLine, JournalLine.account_id == Account.id)
        .group_by(Account.name)
    ).all()
    return {name: int(total) for name, total in rows}


def test_a_transfer_rule_posts_one_move_between_the_two_accounts(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    _apply(session, _transfer_rule("Savings")).unwrap()
    rows = cash_rows([statement_row(date(2026, 4, 3), -500, "Move to savings", "Erika Beispiel", SAVINGS_IBAN)])

    assert ImportStatement(session).execute("Checking", rows).unwrap() == 1

    assert session.query(JournalEntry).count() == 1
    assert _balances(session) == {"Checking": -500, "Savings": 500}
    assert not any(name in _balances(session) for name in (*BUCKETS, "Groceries"))


def test_the_classification_tells_a_rule_made_transfer_apart(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    _apply(session, _transfer_rule("Savings") + '\n[[rule]]\naccount = "Groceries"\n[rule.when]\ndescription = "aldi"\n').unwrap()
    rows = cash_rows([
        statement_row(date(2026, 4, 3), -500, "Move to savings", "Erika Beispiel", SAVINGS_IBAN),
        statement_row(date(2026, 4, 4), -20, "ALDI", "ALDI SUED"),
        statement_row(date(2026, 4, 5), -7, "Coffee"),
    ])

    ImportStatement(session).execute("Checking", rows).unwrap()

    by_description = {
        c.entry.description: c
        for c in session.query(Classification).all()
    }
    transfer = by_description["Move to savings"]
    assert transfer.kind is ClassificationKind.transfer
    assert transfer.corrected is False and transfer.mirror_of_entry_id is None
    assert transfer.matched_rule is not None and transfer.matched_rule.kind is RuleKind.transfer
    assert transfer.final_account.name == "Savings"
    assert transfer.proposed_account_id == transfer.final_account_id
    assert by_description["ALDI"].kind is ClassificationKind.category
    assert by_description["Coffee"].kind is ClassificationKind.category


def test_an_account_rule_onto_an_asset_clearing_account_keeps_its_meaning(
    session: Session, cash_rows, statement_row
) -> None:
    AddAccount(session).execute("Checking", AccountType.asset)
    AddAccount(session).execute("Transfers", AccountType.asset)
    _apply(session, f'[[rule]]\naccount = "Transfers"\n[rule.when]\niban = "{SAVINGS_IBAN}"\n').unwrap()
    rows = cash_rows([statement_row(date(2026, 4, 3), -500, "Move", "Erika Beispiel", SAVINGS_IBAN)])

    ImportStatement(session).execute("Checking", rows).unwrap()

    assert session.query(Rule).one().kind is RuleKind.category
    assert session.query(Classification).one().kind is ClassificationKind.category


def test_the_import_is_one_audit_trail_group(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    _apply(session, _transfer_rule("Savings")).unwrap()
    before = session.query(OperationGroup).count()
    rows = cash_rows([
        statement_row(date(2026, 4, 3), -500, "Move to savings", "Erika Beispiel", SAVINGS_IBAN),
        statement_row(date(2026, 4, 4), -20, "ALDI"),
    ])

    ImportStatement(session).execute("Checking", rows).unwrap()

    assert session.query(OperationGroup).count() == before + 1


def test_a_fault_part_way_leaves_nothing_written_and_no_group(
    session: Session, cash_rows, statement_row, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ledger(session)
    _apply(session, _transfer_rule("Savings")).unwrap()
    entries = session.query(JournalEntry).count()
    groups = session.query(OperationGroup).count()
    real = journal_module.add_classification_service
    calls = []

    def flaky(*args, **kwargs):
        calls.append(args)
        if len(calls) == 2:
            return Result.err(RuntimeError("boom"))
        return real(*args, **kwargs)

    monkeypatch.setattr(journal_module, "add_classification_service", flaky)
    rows = cash_rows([
        statement_row(date(2026, 4, 3), -500, "Move to savings", "Erika Beispiel", SAVINGS_IBAN),
        statement_row(date(2026, 4, 4), -20, "ALDI"),
    ])

    assert ImportStatement(session).execute("Checking", rows).is_err

    assert session.query(JournalEntry).count() == entries
    assert session.query(OperationGroup).count() == groups
    assert session.query(Classification).count() == 0


def test_a_transfer_rule_never_matches_a_row_imported_into_its_own_counterpart(
    session: Session, cash_rows, statement_row
) -> None:
    _ledger(session)
    text = _transfer_rule("Savings") + '\n[[rule]]\naccount = "Groceries"\n[rule.when]\niban = "' + SAVINGS_IBAN + '"\n'
    _apply(session, text).unwrap()
    rows = cash_rows([statement_row(date(2026, 4, 4), 500, "Move to savings", "Erika Beispiel", SAVINGS_IBAN)])

    ImportStatement(session).execute("Savings", rows).unwrap()

    classification = session.query(Classification).one()
    assert classification.kind is ClassificationKind.category
    assert classification.final_account.name == "Groceries"


def test_the_row_falls_to_its_bucket_when_only_the_skipped_rule_matches(
    session: Session, cash_rows, statement_row
) -> None:
    _ledger(session)
    _apply(session, _transfer_rule("Savings")).unwrap()
    rows = cash_rows([statement_row(date(2026, 4, 4), 500, "Move to savings", "Erika Beispiel", SAVINGS_IBAN)])

    ImportStatement(session).execute("Savings", rows).unwrap()

    classification = session.query(Classification).one()
    assert classification.final_account.name == "Unclassified Income"
    assert classification.matched_rule_id is None


def test_a_leaf_asset_or_liability_counterpart_is_accepted(session: Session) -> None:
    AddAccount(session).execute("Card", AccountType.liability)
    AddAccount(session).execute("Cash", AccountType.asset)
    text = _transfer_rule("Card") + "\n" + _transfer_rule("Cash", "DE02120300000000202051")

    assert _apply(session, text).is_ok
    assert [r.kind for r in session.query(Rule).order_by(Rule.id)] == [RuleKind.transfer, RuleKind.transfer]


@pytest.mark.parametrize(
    ("account", "message"),
    [
        ("Groceries", "rule 1, transfer: 'Groceries' is an expense account; a transfer's counterpart must be an own asset or liability account"),
        ("Salary", "rule 1, transfer: 'Salary' is an income account; a transfer's counterpart must be an own asset or liability account"),
        ("Unclassified Expense", "rule 1, transfer: 'Unclassified Expense' is an expense account"),
        ("Unclassified Income", "rule 1, transfer: 'Unclassified Income' is an income account"),
        ("Alice", "rule 1, transfer: 'Alice' is a People account; money to or from a person stays with split-line"),
    ],
)
def test_a_counterpart_that_is_not_an_own_account_is_refused_naming_the_rule(
    session: Session, people_root, account: str, message: str
) -> None:
    AddAccount(session).execute("Groceries", AccountType.expense)
    AddAccount(session).execute("Salary", AccountType.income)
    AddAccount(session).execute("Unclassified Expense", AccountType.expense)
    AddAccount(session).execute("Unclassified Income", AccountType.income)
    AddAccount(session).execute("Alice", AccountType.asset, parent_name="People")

    result = _apply(session, _transfer_rule(account))

    assert result.is_err and str(result.unwrap_err()).startswith(message)
    assert session.query(Rule).count() == 0


def test_a_missing_or_non_leaf_counterpart_is_refused_under_the_transfer_key(session: Session) -> None:
    AddAccount(session).execute("Savings", AccountType.asset)
    AddAccount(session).execute("Holiday", AccountType.asset, parent_name="Savings")

    assert str(_apply(session, _transfer_rule("Nowhere")).unwrap_err()) == "rule 1, transfer: no account named 'Nowhere'"
    assert "rule 1, transfer: 'Savings' has sub-accounts" in str(_apply(session, _transfer_rule("Savings")).unwrap_err())


def test_the_kind_is_part_of_the_identity_so_changing_it_retires_the_rule(session: Session) -> None:
    _ledger(session)
    _apply(session, f'[[rule]]\naccount = "Savings"\n[rule.when]\niban = "{SAVINGS_IBAN}"\n').unwrap()

    plan = _apply(session, _transfer_rule("Savings")).unwrap()

    assert (len(plan.added), len(plan.retired)) == (1, 1)
    kinds = [(r.kind, r.deleted_at is None) for r in session.query(Rule).order_by(Rule.id)]
    assert kinds == [(RuleKind.category, False), (RuleKind.transfer, True)]
    assert 'transfer = "Savings"' in ShowRules(session).execute().unwrap()


def test_a_ledger_without_transfer_rules_imports_as_before(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    rows = cash_rows([statement_row(date(2026, 4, 3), -500, "Move", "Erika Beispiel", SAVINGS_IBAN)])

    ImportStatement(session).execute("Checking", rows).unwrap()

    assert _balances(session) == {"Checking": -500, "Unclassified Expense": 500}
    assert session.query(Classification).one().kind is ClassificationKind.category
