"""Layer 1 — pure unit tests, no fixture.

The `record-split` --line parser (issue 006). Parsing
ACCOUNT:QUANTITY:UNIT:PRICE:SIDE is the one place the CLI is allowed to
reject input, because it cannot construct a use-case call from a malformed
value. See dev/design/cli-record-and-balances.md.
"""

from decimal import Decimal

import click
import pytest

from kohle.app.cli.cli import _parse_line
from kohle.use_cases.journal import LineInput


def test_well_formed_line_parses_to_expected_fields() -> None:
    line = _parse_line("Groceries:10:EUR:1:debit")
    assert line == LineInput("Groceries", Decimal(10), "EUR", Decimal(1), is_debit=True)


def test_credit_side_maps_to_is_debit_false() -> None:
    line = _parse_line("Checking:10:EUR:1:credit")
    assert line.is_debit is False


def test_wrong_field_count_names_the_offending_value() -> None:
    with pytest.raises(click.BadParameter) as exc_info:
        _parse_line("Groceries:10:EUR:debit")
    assert "Groceries:10:EUR:debit" in str(exc_info.value)


def test_side_outside_debit_or_credit_is_rejected() -> None:
    with pytest.raises(click.BadParameter) as exc_info:
        _parse_line("Groceries:10:EUR:1:dr")
    assert "'dr'" in str(exc_info.value)


def test_non_numeric_quantity_is_rejected() -> None:
    with pytest.raises(click.BadParameter) as exc_info:
        _parse_line("Groceries:ten:EUR:1:debit")
    assert "'ten'" in str(exc_info.value)


def test_non_numeric_price_is_rejected() -> None:
    with pytest.raises(click.BadParameter) as exc_info:
        _parse_line("Groceries:10:EUR:free:debit")
    assert "'free'" in str(exc_info.value)


def test_quantity_and_price_parse_to_decimal_never_float() -> None:
    line = _parse_line("Groceries:0.1:EUR:1.1:debit")
    assert line.quantity == Decimal("0.1")
    assert line.unit_price == Decimal("1.1")
    assert isinstance(line.quantity, Decimal)
    assert isinstance(line.unit_price, Decimal)
