"""Characterisation of the Deutsche Bank plugin (issue 025), written against the current code first."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from kohle.app.plugins.kohle_deutsche_bank_importer import (
    CsvError,
    DeustcheBankStatementImporter,
    InvalidStructureError,
    MissingFieldError,
    MissingSectionError,
    _optional_cell,
)
from kohle.domain.models import AccountType, Classification, JournalEntry
from kohle.plugin.importer_plugin import StatementUnreadable
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.journal import ImportStatement
from kohle.use_cases.rules import AddRule

FIXTURE = Path(__file__).parent / "fixtures" / "deutsche_bank_statement.csv"

def test_deutsche_bank_import_ledger_rows_unchanged(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    AddAccount(session).execute("Groceries", AccountType.expense)
    AddRule(session).execute("ALDI", "Groceries").unwrap()

    rows = DeustcheBankStatementImporter().import_statement(str(FIXTURE)).unwrap()
    assert ImportStatement(session).execute("Checking", rows).unwrap() == 4

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


def _import(path: Path):
    return DeustcheBankStatementImporter().import_statement(str(path))


def test_references_are_content_derived_and_deterministic() -> None:
    first = _import(FIXTURE).unwrap()
    second = _import(FIXTURE).unwrap()

    assert [r.reference for r in first] == [r.reference for r in second]
    assert len({r.reference for r in first}) == len(first)


def test_rows_identical_in_date_amount_and_description_share_a_reference(tmp_path: Path) -> None:
    lines = FIXTURE.read_text().splitlines()
    duplicate = lines[:-1] + [lines[-2], lines[-1]]
    path = tmp_path / "dup.csv"
    path.write_text("\n".join(duplicate))

    rows = _import(path).unwrap()

    assert rows[-1].reference == rows[-2].reference


@pytest.mark.parametrize(
    ("value", "expected"),
    [(pd.NA, None), (float("nan"), None), ("REWE", "REWE")],
)
def test_optional_cell_maps_missing_to_none(value, expected) -> None:
    assert _optional_cell(value) == expected


def test_unreadable_path_is_a_named_error(tmp_path: Path) -> None:
    err = _import(tmp_path / "missing.csv").unwrap_err()

    assert isinstance(err, StatementUnreadable)
    assert "missing.csv" in str(err)


def test_undecodable_file_is_a_named_error(tmp_path: Path) -> None:
    path = tmp_path / "latin1.csv"
    path.write_bytes(b"AktivKonto;\xe4\xf6\xfc")

    assert isinstance(_import(path).unwrap_err(), StatementUnreadable)


@pytest.mark.parametrize(
    "text",
    [
        "nothing useful here",
        "\n".join(FIXTURE.read_text().splitlines()[:4] + ["Booking date;Value date"]),
        "\n".join(FIXTURE.read_text().splitlines()[:-1]),
    ],
)
def test_unparseable_statement_is_a_named_error_with_a_message(tmp_path: Path, text: str) -> None:
    path = tmp_path / "bad.csv"
    path.write_text(text)

    err = _import(path).unwrap_err()

    assert isinstance(err, (MissingFieldError, MissingSectionError, InvalidStructureError, CsvError))
    assert str(err)
