"""validate_statement, pure, no database (issues 026, 027)."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from kohle.domain.domain_errors import (
    DuplicateReferenceInStatement,
    MalformedStatementRow,
)
from kohle.plugin.importer_plugin import CashRow, SecurityRow
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


def _trade(reference: str = "t", **overrides) -> SecurityRow:
    return replace(
        SecurityRow(
            entry_date=date(2026, 3, 1),
            reference=reference,
            description="Buy",
            instrument_identifier="X1",
            quantity=Decimal(1),
            unit_price=Decimal(10),
        ),
        **overrides,
    )


def test_a_reference_repeated_across_cash_and_security_rows_is_rejected() -> None:
    error = validate_statement([_cash("a"), _trade("a")])

    assert isinstance(error, DuplicateReferenceInStatement)
    assert (error.first_row_number, error.row_number) == (1, 2)


@pytest.mark.parametrize("price", [None, Decimal(0), Decimal(-1), Decimal("NaN"), Decimal("Infinity")])
def test_a_bad_unit_price_is_malformed(price) -> None:
    error = validate_statement([_cash("a"), _trade(unit_price=price)])

    assert isinstance(error, MalformedStatementRow)
    assert (error.row_number, error.field) == (2, "unit_price")


@pytest.mark.parametrize("quantity", [None, Decimal(0), Decimal("NaN")])
def test_a_bad_quantity_is_malformed(quantity) -> None:
    error = validate_statement([_trade(quantity=quantity)])

    assert isinstance(error, MalformedStatementRow)
    assert (error.row_number, error.field) == (1, "quantity")


@pytest.mark.parametrize("identifier", ["", "  ", None])
def test_an_empty_instrument_identifier_is_malformed(identifier) -> None:
    error = validate_statement([_trade(instrument_identifier=identifier)])

    assert isinstance(error, MalformedStatementRow)
    assert error.field == "instrument_identifier"


def test_a_clean_mixed_list_returns_none() -> None:
    assert validate_statement([_cash("a"), _trade("b"), _trade("c", quantity=Decimal(-2))]) is None


def test_a_security_row_without_a_price_does_not_construct() -> None:
    with pytest.raises(TypeError):
        SecurityRow(  # type: ignore[call-arg]
            entry_date=date(2026, 3, 1),
            reference="t",
            description="x",
            instrument_identifier="X1",
            quantity=Decimal(1),
        )
