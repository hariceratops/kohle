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
from sqlalchemy import select

from kohle.app.cli.cli import cli
from kohle.db.schema import alembic_config
from kohle.domain.models import Price, Unit
from kohle.use_cases.sampling import parse_sampling_rules, render_sampling_rules, sample_dates
from tests.test_portfolio_cli import _ledger, _pin_today

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
