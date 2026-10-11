"""Layer 1 — pure unit tests with temp files.

`FilePriceFetcher` (issue 030), design §9.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from kohle.app.plugins.kohle_file_price_fetcher import (
    FilePriceFetcher,
    MalformedPriceFile,
    PriceFileUnreadable,
)
from kohle.plugin.price_plugin import (
    Close,
    MissingEnvironmentVariable,
    Unavailable,
    UnavailableReason,
)

HEADER = "identifier,date,close\n"


def _price_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> Path:
    path = tmp_path / "prices.csv"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setenv("KOHLE_PRICE_FILE", str(path))
    return path


def test_name_is_file() -> None:
    assert FilePriceFetcher().name == "file"


@pytest.mark.parametrize("value", [None, ""])
def test_unset_or_empty_variable_is_a_plugin_error(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv("KOHLE_PRICE_FILE", raising=False)
    else:
        monkeypatch.setenv("KOHLE_PRICE_FILE", value)

    err = FilePriceFetcher().fetch_latest_closes(["XYZ"]).unwrap_err()

    assert isinstance(err, MissingEnvironmentVariable)
    assert "KOHLE_PRICE_FILE is not set" in str(err)


def test_missing_file_is_a_plugin_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KOHLE_PRICE_FILE", str(tmp_path / "absent.csv"))

    err = FilePriceFetcher().fetch_latest_closes(["XYZ"]).unwrap_err()

    assert isinstance(err, PriceFileUnreadable)


def test_undecodable_file_is_a_plugin_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "prices.csv"
    path.write_bytes(b"identifier,date,close\n\xff\xfe,2026-01-01,1\n")
    monkeypatch.setenv("KOHLE_PRICE_FILE", str(path))

    err = FilePriceFetcher().fetch_latest_closes(["XYZ"]).unwrap_err()

    assert isinstance(err, PriceFileUnreadable)


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ("id,date,close\nXYZ,2026-01-01,1\n", "header"),
        (HEADER + "XYZ,2026-01-01\n", "Line 2"),
        (HEADER + ",2026-01-01,1\n", "identifier"),
        (HEADER + "XYZ,01/02/2026,1\n", "date"),
        (HEADER + "XYZ,2026-01-01,abc\n", "close"),
    ],
)
def test_malformed_rows_are_plugin_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str, fragment: str
) -> None:
    _price_file(tmp_path, monkeypatch, body)

    err = FilePriceFetcher().fetch_latest_closes(["XYZ"]).unwrap_err()

    assert isinstance(err, MalformedPriceFile)
    assert fragment in str(err)


def test_repeated_identifier_and_date_is_a_plugin_error_with_its_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _price_file(tmp_path, monkeypatch, HEADER + "XYZ,2026-01-01,1\nOTHER,2026-01-01,2\nXYZ,2026-01-01,3\n")

    err = FilePriceFetcher().fetch_latest_closes(["XYZ"]).unwrap_err()

    assert isinstance(err, MalformedPriceFile)
    assert err.line == 4


def test_latest_row_per_symbol_wins_and_blank_lines_are_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _price_file(tmp_path, monkeypatch, HEADER + "XYZ,2026-01-05,12.5\n\nXYZ,2026-01-02,10\n OTHER , 2026-01-01 , 7 \n")

    results = FilePriceFetcher().fetch_latest_closes(["XYZ", "OTHER"]).unwrap()

    assert results == {
        "XYZ": Close(price_date=date(2026, 1, 5), price=Decimal("12.5"), currency="EUR"),
        "OTHER": Close(price_date=date(2026, 1, 1), price=Decimal(7), currency="EUR"),
    }


def test_absent_symbol_is_unavailable_and_unrequested_rows_are_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _price_file(tmp_path, monkeypatch, HEADER + "OTHER,2026-01-01,7\n")

    results = FilePriceFetcher().fetch_latest_closes(["XYZ"]).unwrap()

    assert set(results) == {"XYZ"}
    unavailable = results["XYZ"]
    assert isinstance(unavailable, Unavailable)
    assert unavailable.reason is UnavailableReason.no_symbol
    assert str(path) in unavailable.detail


def test_zero_close_passes_through_for_core_to_validate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _price_file(tmp_path, monkeypatch, HEADER + "XYZ,2026-01-01,0\n")

    results = FilePriceFetcher().fetch_latest_closes(["XYZ"]).unwrap()

    assert results["XYZ"] == Close(price_date=date(2026, 1, 1), price=Decimal(0), currency="EUR")
