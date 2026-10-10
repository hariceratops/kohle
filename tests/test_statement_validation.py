"""validate_statement, pure, no database (issues 026, 027)."""

from datetime import date
from decimal import Decimal

import pytest

from kohle.domain.domain_errors import (
    DuplicateReferenceInStatement,
    MalformedStatementRow,
)
from kohle.plugin.importer_plugin import CashRow
from kohle.use_cases.journal import validate_statement


def _cash(reference: str) -> CashRow:
    return CashRow(
        entry_date=date(2026, 3, 1),
        reference=reference,
        description="x",
        amount=Decimal(1),
        counterparty_name=None,
        counterparty_iban=None,
    )


@pytest.mark.parametrize("reference", ["", "   ", "\t\n", None])
def test_an_absent_or_blank_reference_is_malformed(reference) -> None:
    error = validate_statement([_cash("ok"), _cash(reference)])

    assert isinstance(error, MalformedStatementRow)
    assert (error.row_number, error.field) == (2, "reference")


def test_a_reference_repeated_across_cash_rows_is_rejected() -> None:
    error = validate_statement([_cash("a"), _cash("b"), _cash("a")])

    assert isinstance(error, DuplicateReferenceInStatement)
    assert (error.reference, error.first_row_number, error.row_number) == ("a", 1, 3)


def test_references_differing_only_in_whitespace_are_duplicates() -> None:
    assert isinstance(validate_statement([_cash("a"), _cash(" a ")]), DuplicateReferenceInStatement)


def test_a_clean_list_returns_none() -> None:
    assert validate_statement([_cash("a"), _cash("b")]) is None
    assert validate_statement([]) is None


def test_validate_statement_rejects_malformed_security_rows() -> None:
    # TODO(027): duplicate across cash+security; unit_price None/0/-1/NaN; quantity 0; empty instrument_identifier; clean mixed list returns None; SecurityRow without unit_price raises TypeError.
    pytest.skip("security rows land with issue 027")
