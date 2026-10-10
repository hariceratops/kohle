"""Characterisation of the Deutsche Bank plugin (issue 025), written against the current code first."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from kohle.app.plugins.kohle_deutsche_bank_importer import DeustcheBankStatementImporter
from kohle.domain.models import AccountType, Classification, JournalEntry
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.journal import ImportStatement
from kohle.use_cases.rules import AddRule

FIXTURE = Path(__file__).parent / "fixtures" / "deutsche_bank_statement.csv"

# TODO (not yet written): content-derived reference is deterministic, identical
# rows collide, differing rows differ; pd.NA/nan normalisation cases moved from
# test_optional_str_normalises_a_statement_cell; unreadable file gives a named error.


def test_deutsche_bank_import_ledger_rows_unchanged(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    AddAccount(session).execute("Groceries", AccountType.expense)
    AddRule(session).execute("ALDI", "Groceries").unwrap()

    df = DeustcheBankStatementImporter().import_statement(str(FIXTURE)).unwrap()
    assert ImportStatement(session).execute("Checking", df).unwrap() == 4

    entries = session.scalars(select(JournalEntry).order_by(JournalEntry.entry_date)).all()
    snapshot = [
        (
            e.entry_date,
            e.description,
            e.counterparty_name,
            e.counterparty_iban,
            sorted(
                (l.account.name, l.unit.identifier, l.quantity, l.unit_price, l.is_debit)
                for l in e.lines
            ),
        )
        for e in entries
    ]

    def cash(account: str, quantity: str, is_debit: bool) -> tuple:
        return (account, "EUR", Decimal(quantity), Decimal(1), is_debit)

    assert snapshot == [
        (
            date(2026, 3, 16),
            "Rent March",
            "Max Mustermann",
            "DE02120300000000202051",
            sorted([cash("Checking", "950", False), cash("Unclassified Expense", "950", True)]),
        ),
        # The card payment is dated from the timestamp in Payment Details, not
        # from the booking date (03/18).
        (
            date(2026, 3, 17),
            "Card 0001 ALDI SUED 17-03-2026T18:45:12 purchase",
            "ALDI SUED",
            None,
            sorted([cash("Checking", "42.3", False), cash("Groceries", "42.3", True)]),
        ),
        (
            date(2026, 3, 25),
            "Salary March",
            "ACME GmbH",
            "DE75512108001245126199",
            sorted([cash("Checking", "2500", True), cash("Unclassified Income", "2500", False)]),
        ),
        (
            date(2026, 3, 27),
            "Account fee",
            None,
            None,
            sorted([cash("Checking", "5.9", False), cash("Unclassified Expense", "5.9", True)]),
        ),
    ]

    classifications = {
        c.entry.description: (c.proposed_account_id, c.final_account_id, c.matched_rule_id is not None, c.corrected)
        for c in session.scalars(select(Classification))
    }
    names = {e.description: [l.account for l in e.lines] for e in entries}
    for description, (proposed, final, matched, corrected) in classifications.items():
        counterpart = next(a for a in names[description] if a.name != "Checking")
        assert proposed == final == counterpart.id
        assert matched == (description.startswith("Card 0001"))
        assert corrected is False
