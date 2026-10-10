"""import-statement CLI (issue 027)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from kohle.app.cli.cli import cli
from kohle.core.result import Result
from kohle.domain.models import AccountType, JournalEntry, UnitKind
from kohle.plugin.importer_plugin import (
    CashRow,
    ImportError,
    SecurityRow,
    StatementImporterPlugin,
    StatementRow,
)
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.units import AddUnit


class _Unreadable(ImportError):
    def __str__(self) -> str:
        return "cannot make sense of this file"


class _FakePlugin(StatementImporterPlugin):
    def __init__(self, rows: list[StatementRow] | None = None) -> None:
        self.rows = rows

    @property
    def name(self) -> str:
        return "fake"

    def import_statement(self, statement_path: str) -> Result[list[StatementRow], ImportError]:
        if self.rows is None:
            return Result.err(_Unreadable())
        return Result.ok(self.rows)


_TRADE = SecurityRow(
    entry_date=date(2026, 3, 2),
    reference="T-1",
    description="Buy X",
    instrument_identifier="X1",
    quantity=Decimal(10),
    unit_price=Decimal("95.50"),
)
_CASH = CashRow(
    entry_date=date(2026, 3, 3),
    reference="C-1",
    description="Gift",
    amount=Decimal(5),
    counterparty_name=None,
    counterparty_iban=None,
)


@pytest.fixture
def statement_file(tmp_path: Path) -> str:
    path = tmp_path / "statement.csv"
    path.write_text("")
    return str(path)


def _run(session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch, plugin, *args: str):
    monkeypatch.setattr("kohle.app.cli.cli.load_plugins", lambda: {"fake": plugin})
    return CliRunner().invoke(cli, ["import-statement", "fake", *args], obj=session_factory)


def _entry_count(session_factory: sessionmaker) -> int:
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(JournalEntry))


@pytest.fixture
def ledger(session_factory: sessionmaker) -> sessionmaker:
    with session_factory() as session:
        AddAccount(session).execute("Cash", AccountType.asset).unwrap()
        AddAccount(session).execute("Depot", AccountType.asset).unwrap()
        AddUnit(session).execute("X1", "X", UnitKind.security).unwrap()
    return session_factory


def test_import_statement_four_positional_form(
    ledger: sessionmaker, monkeypatch: pytest.MonkeyPatch, statement_file: str
) -> None:
    result = _run(ledger, monkeypatch, _FakePlugin([_TRADE]), "Cash", "Depot", statement_file)

    assert result.exit_code == 0, result.output
    assert "1 entries imported" in result.output


def test_three_positional_form_still_parses(
    ledger: sessionmaker, monkeypatch: pytest.MonkeyPatch, statement_file: str
) -> None:
    result = _run(ledger, monkeypatch, _FakePlugin([_CASH]), "Cash", statement_file)

    assert result.exit_code == 0, result.output
    assert "1 entries imported" in result.output


def test_trades_without_an_instrument_account_are_refused(
    ledger: sessionmaker, monkeypatch: pytest.MonkeyPatch, statement_file: str
) -> None:
    result = _run(ledger, monkeypatch, _FakePlugin([_TRADE]), "Cash", statement_file)

    assert result.exit_code != 0
    assert "instrument account" in result.output
    assert _entry_count(ledger) == 0


def test_two_instrument_accounts_is_a_usage_error(
    ledger: sessionmaker, monkeypatch: pytest.MonkeyPatch, statement_file: str
) -> None:
    result = _run(ledger, monkeypatch, _FakePlugin([_TRADE]), "Cash", "Depot", "Depot2", statement_file)

    assert result.exit_code == 2
    assert "INSTRUMENT_ACCOUNT" in result.output
    assert _entry_count(ledger) == 0


def test_a_plugin_error_exits_non_zero_with_its_message(
    ledger: sessionmaker, monkeypatch: pytest.MonkeyPatch, statement_file: str
) -> None:
    result = _run(ledger, monkeypatch, _FakePlugin(None), "Cash", "Depot", statement_file)

    assert result.exit_code != 0
    assert "cannot make sense of this file" in result.output
