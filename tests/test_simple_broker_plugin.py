"""Simple broker CSV parser (issue 028)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from kohle.app.plugins.kohle_simple_broker_importer import (
    HEADER,
    MalformedField,
    SimpleBrokerStatementImporter,
    UnexpectedHeader,
    UnknownRowType,
)
from kohle.plugin.importer_plugin import CashRow, SecurityRow, StatementUnreadable
from kohle.plugin.plugin_manager import load_plugins

FIXTURE = Path(__file__).parent / "fixtures" / "simple_broker.csv"
ISIN = "DE0005190003"


def _statement(tmp_path: Path, *lines: str, header: str = ",".join(HEADER)) -> str:
    path = tmp_path / "statement.csv"
    path.write_text("\n".join([header, *lines]) + "\n", encoding="utf-8")
    return str(path)


def test_parses_buy_sell_and_dividend_rows() -> None:
    rows = SimpleBrokerStatementImporter().import_statement(str(FIXTURE)).unwrap()

    assert rows == [
        SecurityRow(
            entry_date=date(2026, 3, 2),
            reference="T-1001",
            description=f"Buy {ISIN}",
            instrument_identifier=ISIN,
            quantity=Decimal(10),
            unit_price=Decimal("95.50"),
        ),
        SecurityRow(
            entry_date=date(2026, 3, 20),
            reference="T-1002",
            description=f"Sell {ISIN}",
            instrument_identifier=ISIN,
            quantity=Decimal(-4),
            unit_price=Decimal("101.25"),
        ),
        CashRow(
            entry_date=date(2026, 4, 15),
            reference="D-2001",
            description=f"Dividend {ISIN}",
            amount=Decimal("12.40"),
            counterparty_name=None,
            counterparty_iban=None,
        ),
    ]


def test_dividend_without_isin_has_a_bare_description(tmp_path: Path) -> None:
    path = _statement(tmp_path, "2026-04-15,D-1,dividend,,,,5.00")

    (row,) = SimpleBrokerStatementImporter().import_statement(path).unwrap()

    assert row.description == "Dividend"


def test_blank_lines_are_skipped(tmp_path: Path) -> None:
    path = _statement(tmp_path, "", f"2026-03-02,T-1,buy,{ISIN},1,10,", "")

    assert len(SimpleBrokerStatementImporter().import_statement(path).unwrap()) == 1


def test_wrong_header(tmp_path: Path) -> None:
    path = _statement(tmp_path, header="date,reference,type")

    error = SimpleBrokerStatementImporter().import_statement(path).unwrap_err()

    assert isinstance(error, UnexpectedHeader)
    assert error.found == ["date", "reference", "type"]


def test_unknown_type_is_a_named_error_with_its_line(tmp_path: Path) -> None:
    path = _statement(tmp_path, f"2026-03-02,T-1,buy,{ISIN},1,10,", f"2026-03-03,T-2,split,{ISIN},1,10,")

    error = SimpleBrokerStatementImporter().import_statement(path).unwrap_err()

    assert isinstance(error, UnknownRowType)
    assert (error.line, error.value) == (3, "split")
    assert "split" in str(error)


@pytest.mark.parametrize(
    ("line", "column"),
    [
        (f"2026-03-02,T-1,buy,{ISIN},ten,10,", "quantity"),
        (f"2026-03-02,T-1,buy,{ISIN},1,NaN,", "price"),
        (f"2026-03-02,T-1,buy,{ISIN},1,Infinity,", "price"),
        (f"2026-03-02,T-1,sell,{ISIN},-4,10,", "quantity"),
        (f"2026-03-02,T-1,buy,{ISIN},0,10,", "quantity"),
        (f"2026-03-02,T-1,buy,{ISIN},1,0,", "price"),
        (f"2026-03-02,T-1,buy,{ISIN},1,10,5.00", "amount"),
        ("2026-03-02,T-1,buy,,1,10,", "isin"),
        (f"2026-03-02,T-1,buy,{ISIN},,10,", "quantity"),
        (f"2026-03-02,T-1,dividend,{ISIN},3,,5.00", "quantity"),
        (f"2026-03-02,T-1,dividend,{ISIN},,10,5.00", "price"),
        (f"2026-03-02,T-1,dividend,{ISIN},,,", "amount"),
        (f"2026-03-02,T-1,dividend,{ISIN},,,abc", "amount"),
        (f"2026-03-02,T-1,dividend,{ISIN},,,NaN", "amount"),
        (f"02/03/2026,T-1,buy,{ISIN},1,10,", "date"),
        (f",T-1,buy,{ISIN},1,10,", "date"),
        ("2026-03-02,T-1,buy", "row"),
    ],
)
def test_malformed_fields_name_the_column_and_line(tmp_path: Path, line: str, column: str) -> None:
    path = _statement(tmp_path, f"2026-03-01,T-0,buy,{ISIN},1,10,", line)

    error = SimpleBrokerStatementImporter().import_statement(path).unwrap_err()

    assert isinstance(error, MalformedField)
    assert (error.line, error.column) == (3, column)
    assert str(error).startswith("Line 3")


def test_unreadable_path(tmp_path: Path) -> None:
    error = SimpleBrokerStatementImporter().import_statement(str(tmp_path / "missing.csv")).unwrap_err()

    assert isinstance(error, StatementUnreadable)


def test_undecodable_file(tmp_path: Path) -> None:
    path = tmp_path / "latin1.csv"
    path.write_bytes(",".join(HEADER).encode() + b"\n2026-03-02,T\xe4,buy,X,1,1,\n")

    error = SimpleBrokerStatementImporter().import_statement(str(path)).unwrap_err()

    assert isinstance(error, StatementUnreadable)


def test_field_over_the_csv_limit_is_an_error_not_an_exception(tmp_path: Path) -> None:
    path = tmp_path / "huge.csv"
    path.write_text(",".join(HEADER) + "\n2026-03-02," + "x" * 200_000 + ",dividend,,,,1.00\n")

    error = SimpleBrokerStatementImporter().import_statement(str(path)).unwrap_err()

    assert isinstance(error, StatementUnreadable)


def test_discovered_through_the_entry_point_group() -> None:
    # A failure here on a stale install means run `uv sync`, not a bug.
    assert isinstance(load_plugins()["kohle-simple-broker"], SimpleBrokerStatementImporter)
