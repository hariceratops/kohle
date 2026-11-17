"""Layer 2 — join, unjoin, reclassify and split-line on transfers (issues 129-131). Design §18.4."""

from datetime import date

import pytest
from sqlalchemy.orm import Session

from kohle.domain.models import AccountType, OperationGroup
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.journal import ImportStatement
from kohle.use_cases.rules import ApplyRuleFile, PlanRuleFile
from kohle.use_cases.transfers import ListUnmirroredTransfers

SAVINGS_IBAN = "DE44500105175407324931"


def _transfer_rule(account: str, iban: str = SAVINGS_IBAN) -> str:
    text = f'[[rule]]\ntransfer = "{account}"\n[rule.when]\niban = "{iban}"\n'
    return text


def _ledger(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset)
    AddAccount(session).execute("Savings", AccountType.asset)
    text = _transfer_rule("Savings")
    plan = PlanRuleFile(session).execute(text).unwrap()
    ApplyRuleFile(session).execute(text, plan.base).unwrap()


@pytest.mark.skip(reason="scaffold")
def test_reclassify_transfer_line_to_category_unabsorbs_mirror() -> None:
    # TODO: §18.4: reclassify one test per cell of §7.1, join-transfer refusals and a late join, unjoin-transfer, split-line refusals
    ...


def test_a_transfer_to_an_account_with_a_statement_is_listed_until_its_mirror_arrives(
    session: Session, cash_rows, statement_row
) -> None:
    _ledger(session)
    ImportStatement(session).execute(
        "Savings", cash_rows([statement_row(date(2026, 4, 1), 10, "Interest", "Bank")])
    ).unwrap()
    ImportStatement(session).execute(
        "Checking",
        cash_rows([statement_row(date(2026, 4, 3), -500, "Move to savings", "Erika", SAVINGS_IBAN)]),
    ).unwrap()

    listed = ListUnmirroredTransfers(session).execute().unwrap()

    assert [(t.entry_date, t.description, t.amount, t.account_name, t.counterpart_name) for t in listed] == [
        (date(2026, 4, 3), "Move to savings", -500, "Checking", "Savings")
    ]


def test_a_transfer_to_a_counterpart_never_imported_is_not_listed(
    session: Session, cash_rows, statement_row
) -> None:
    _ledger(session)
    ImportStatement(session).execute(
        "Checking",
        cash_rows([statement_row(date(2026, 4, 3), -500, "Move to savings", "Erika", SAVINGS_IBAN)]),
    ).unwrap()

    assert ListUnmirroredTransfers(session).execute().unwrap() == []


def test_a_transfer_whose_mirror_was_absorbed_is_not_listed(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    ImportStatement(session).execute(
        "Checking",
        cash_rows([statement_row(date(2026, 4, 3), -500, "Move to savings", "Erika", SAVINGS_IBAN)]),
    ).unwrap()
    ImportStatement(session).execute(
        "Savings", cash_rows([statement_row(date(2026, 4, 4), 500, "From checking", "Erika")])
    ).unwrap()

    assert ListUnmirroredTransfers(session).execute().unwrap() == []


def test_a_transfer_older_than_the_first_statement_row_by_more_than_the_window_is_not_listed(
    session: Session, cash_rows, statement_row
) -> None:
    _ledger(session)
    ImportStatement(session).execute(
        "Checking",
        cash_rows([
            statement_row(date(2026, 4, 1), -100, "Early", "Erika", SAVINGS_IBAN, reference="a"),
            statement_row(date(2026, 4, 7), -200, "Edge", "Erika", SAVINGS_IBAN, reference="b"),
        ]),
    ).unwrap()
    ImportStatement(session).execute(
        "Savings", cash_rows([statement_row(date(2026, 4, 10), 1, "Interest", "Bank")])
    ).unwrap()

    listed = ListUnmirroredTransfers(session).execute().unwrap()

    assert [t.description for t in listed] == ["Edge"]


def test_listing_writes_no_operation_group(session: Session, cash_rows, statement_row) -> None:
    _ledger(session)
    ImportStatement(session).execute(
        "Savings", cash_rows([statement_row(date(2026, 4, 1), 10, "Interest", "Bank")])
    ).unwrap()
    ImportStatement(session).execute(
        "Checking",
        cash_rows([statement_row(date(2026, 4, 3), -500, "Move", "Erika", SAVINGS_IBAN)]),
    ).unwrap()
    before = session.query(OperationGroup).count()

    ListUnmirroredTransfers(session).execute().unwrap()

    assert session.query(OperationGroup).count() == before
