"""Layer 2 — migrated ledger reproduces the pre-feature net-worth-history output (issue 064, 069). Design §18.4.

The fixtures were captured from the pre-feature code (`--period-end
last-working-day --state BY`) before it was deleted; they are the oracle.
"""

import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from click.testing import CliRunner
from sqlalchemy import select

from kohle.app.cli.cli import cli
from kohle.db.connection import make_engine, make_session_factory
from kohle.db.schema import alembic_config
from kohle.core.result import Result
from kohle.domain.models import Price, Unit
from kohle.plugin.importer_plugin import CashRow, StatementImporterPlugin
from kohle.use_cases.sampling import (
    parse_sampling_rules,
    render_sampling_rules,
    sample_dates,
)
from tests.test_portfolio_cli import _SETUP, _ledger, _pin_today

FIXTURES = Path(__file__).parent / "fixtures"
DEFAULT = "mid-month: day 15; salary: last workday"


def test_default_list_dates_equal_the_captured_pre_feature_dates() -> None:
    expected = [
        date.fromisoformat(line)
        for line in (FIXTURES / "sample_dates_last_working_day_by.txt").read_text().splitlines()
    ]
    rules = parse_sampling_rules(DEFAULT).unwrap()

    got = [s.on for s in sample_dates(rules, lambda _: "BY", date(2000, 1, 1), date(2040, 12, 31))]

    assert got == expected


def test_default_list_figures_equal_the_captured_pre_feature_output(session_factory, monkeypatch) -> None:
    _pin_today(monkeypatch, date(2029, 6, 20))
    runner = _ledger(session_factory)
    with session_factory() as session:
        unit_id = session.scalars(select(Unit.id).where(Unit.identifier == "X1")).one()
        session.add(Price(unit_id=unit_id, price_date=date(2025, 8, 20), price=Decimal(125), source="file"))
        session.commit()

    result = runner.invoke(
        cli, ["net-worth-history", "--from", "2024-01-01", "--to", "2029-01-31"], obj=session_factory
    )

    assert result.exit_code == 0, result.output
    oracle = (FIXTURES / "net_worth_history_pre_sampling.txt").read_text().splitlines()
    got = result.output.splitlines()
    assert [ln.split()[:6] for ln in got[2:]] == [ln.split()[:6] for ln in oracle[2:]]
    assert got[0].split()[-1] == "role"
    assert [ln.split()[-1] for ln in got[2:] if ln.split()[0] == "2029-01-31"] == ["salary"]


def test_a_ledger_migrated_from_before_the_feature_holds_exactly_the_default_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "kohle.db"
    db.touch()
    monkeypatch.setenv("KOHLE_DB", str(db))
    config = alembic_config()
    command.upgrade(config, "e5a1c3b7d902")

    command.upgrade(config, "head")

    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT rules FROM sampling_rule_lists").fetchall()
    conn.close()
    assert rows == [(DEFAULT,)]
    assert render_sampling_rules(parse_sampling_rules(rows[0][0]).unwrap()) == DEFAULT


def test_a_ledger_migrated_from_state_by_reproduces_the_pre_feature_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_today(monkeypatch, date(2029, 6, 20))
    db = tmp_path / "kohle.db"
    db.touch()
    monkeypatch.setenv("KOHLE_DB", str(db))
    config = alembic_config()
    command.upgrade(config, "f6b2d4c8e013")
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO settings (key, value) VALUES ('state', 'BY')")
    conn.commit()
    conn.close()
    command.upgrade(config, "head")
    session_factory = make_session_factory(make_engine(f"sqlite:///{db}"))
    runner = CliRunner()
    # The migration already created the People root; the fixture ledger adds it itself.
    for args in (a for a in _SETUP if a[1] != "People"):
        assert runner.invoke(cli, args, obj=session_factory).exit_code == 0
    with session_factory() as session:
        unit_id = session.scalars(select(Unit.id).where(Unit.identifier == "X1")).one()
        session.add(Price(unit_id=unit_id, price_date=date(2025, 8, 20), price=Decimal(125), source="file"))
        session.commit()

    result = runner.invoke(
        cli, ["net-worth-history", "--from", "2024-01-01", "--to", "2029-01-31"], obj=session_factory
    )

    assert result.exit_code == 0, result.output
    oracle = (FIXTURES / "net_worth_history_pre_sampling.txt").read_text().splitlines()
    got = result.output.splitlines()
    assert [ln.split()[:6] for ln in got[2:]] == [ln.split()[:6] for ln in oracle[2:]]


# Rule-condition-trees migration (issue 082): the oracle below was written from
# the pre-feature matcher (single regex per rule, first match by (priority, id))
# and run against it before the matcher changed.
_BEFORE_RULE_CONDITIONS = "b8d4f0a6c235"
_IBAN = "DE89370400440532013000"
_ORACLE = {
    "REWE SAGT DANKE": ("Groceries", 1),
    "Miete": ("Rent", 4),
    f"Standing order to {_IBAN}": ("Unclassified Expense", None),
    "Card 4711": ("Misc", 5),
    "AMZN MKTPLACE": ("Misc", 2),
    "Salary": ("Unclassified Income", None),
}


def _cash(day, reference, description, amount, name, iban) -> CashRow:
    return CashRow(
        entry_date=date(2026, 3, day),
        reference=reference,
        description=description,
        amount=amount,
        counterparty_name=name,
        counterparty_iban=iban,
    )


def test_a_ledger_migrated_from_plain_pattern_rules_classifies_as_it_did_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "kohle.db"
    db.touch()
    monkeypatch.setenv("KOHLE_DB", str(db))
    config = alembic_config()
    command.upgrade(config, _BEFORE_RULE_CONDITIONS)
    conn = sqlite3.connect(db)
    for account_id, name, kind in (
        (10, "Cash", "asset"),
        (11, "Groceries", "expense"),
        (12, "Rent", "expense"),
        (13, "Misc", "expense"),
    ):
        conn.execute(
            "INSERT INTO accounts (id, name, type, iban, parent_id, created_at) "
            f"VALUES ({account_id}, '{name}', '{kind}', NULL, NULL, '2026-01-01')"
        )
    for rule_id, pattern, account_id, priority, deleted in (
        (1, "REWE", 11, 100, None),
        (2, "AMZN", 13, 100, None),
        (3, "AMZN", 11, 100, None),
        (4, f"^{_IBAN}$", 12, 50, None),
        (5, "kiosk", 13, 200, None),
        (6, "Salary", 13, 10, "2026-02-01"),
    ):
        conn.execute(
            "INSERT INTO rules (id, pattern, account_id, priority, created_at, deleted_at) "
            "VALUES (?, ?, ?, ?, '2026-01-01', ?)",
            (rule_id, pattern, account_id, priority, deleted),
        )
    conn.commit()
    conn.close()
    command.upgrade(config, "head")
    session_factory = make_session_factory(make_engine(f"sqlite:///{db}"))
    rows = [
        _cash(1, "r1", "REWE SAGT DANKE", Decimal(-20), None, None),
        _cash(2, "r2", "Miete", Decimal(-800), "Vermieter GmbH", _IBAN),
        _cash(3, "r3", f"Standing order to {_IBAN}", Decimal(-50), None, None),
        _cash(4, "r4", "Card 4711", Decimal(-5), "Kiosk Ecke", None),
        _cash(5, "r5", "AMZN MKTPLACE", Decimal(-30), None, None),
        _cash(6, "r6", "Salary", Decimal(2000), None, None),
    ]
    statement = tmp_path / "statement.csv"
    statement.write_text("")

    class _Plugin(StatementImporterPlugin):
        name = "fake"

        def import_statement(self, statement_path: str):
            return Result.ok(rows)

    monkeypatch.setattr("kohle.app.cli.cli.load_plugins", lambda: {"fake": _Plugin()})
    runner = CliRunner()
    assert runner.invoke(cli, ["add-unit", "EUR", "Euro", "--kind", "currency"], obj=session_factory).exit_code == 0
    result = runner.invoke(cli, ["import-statement", "fake", "Cash", str(statement)], obj=session_factory)
    assert result.exit_code == 0, result.output

    conn = sqlite3.connect(db)
    got = {
        description: (account, rule_id)
        for description, account, rule_id in conn.execute(
            "SELECT e.description, a.name, c.matched_rule_id FROM classifications c "
            "JOIN journal_entries e ON e.id = c.journal_entry_id "
            "JOIN accounts a ON a.id = c.final_account_id"
        )
    }
    conn.close()
    assert got == _ORACLE
