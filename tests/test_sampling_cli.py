"""Layer 3 — set/list-sampling-rules, move-state, list-states, net-worth-history --role (issues 065, 068-070). Design §18.7."""

from datetime import date

import pytest
from click.testing import CliRunner
from sqlalchemy import func, select

from kohle.app.cli.cli import cli
from kohle.domain.models import Operation, OperationGroup, SamplingRuleList
from tests.test_portfolio_cli import _SETUP, _pin_today


def _ledger(session_factory) -> CliRunner:
    runner = CliRunner()
    for args in _SETUP:
        assert runner.invoke(cli, args, obj=session_factory).exit_code == 0
    return runner


def _history(runner: CliRunner, session_factory, *args: str):
    return runner.invoke(cli, ["net-worth-history", *args], obj=session_factory)


def test_the_role_column_lists_roles_and_leaves_the_non_sample_to_row_empty(session_factory, monkeypatch) -> None:
    _pin_today(monkeypatch, date(2026, 11, 20))
    runner = _ledger(session_factory)

    result = _history(runner, session_factory, "--from", "2026-10-01", "--to", "2026-11-10")

    lines = result.output.splitlines()
    assert result.exit_code == 0, result.output
    assert lines[0].split()[-1] == "role"
    assert [ln.split()[0] for ln in lines[2:]] == ["2026-10-15", "2026-10-30", "2026-11-10"]
    assert [ln.split()[-1] for ln in lines[2:]] == ["mid-month", "salary", "-"]


def test_a_date_reached_by_several_roles_is_one_row_listing_every_role(session_factory, monkeypatch) -> None:
    _pin_today(monkeypatch, date(2026, 11, 20))
    runner = _ledger(session_factory)
    with session_factory() as session:
        session.add(SamplingRuleList(rules="salary: day 15; mid-month: day 15"))
        session.commit()

    result = _history(runner, session_factory, "--from", "2026-10-01", "--to", "2026-10-15")

    rows = result.output.splitlines()[2:]
    assert result.exit_code == 0, result.output
    assert len(rows) == 1
    assert rows[0].split()[0] == "2026-10-15"
    assert rows[0].endswith("mid-month, salary")


def test_the_highest_id_rule_list_is_the_one_in_force(session_factory, monkeypatch) -> None:
    _pin_today(monkeypatch, date(2026, 11, 20))
    runner = _ledger(session_factory)
    with session_factory() as session:
        session.add(SamplingRuleList(rules="salary: day 25"))
        session.commit()

    result = _history(runner, session_factory, "--from", "2026-10-01", "--to", "2026-10-31")

    assert [ln.split()[0] for ln in result.output.splitlines()[2:]] == ["2026-10-25", "2026-10-31"]


def test_period_end_is_gone(session_factory) -> None:
    result = CliRunner().invoke(cli, ["net-worth-history", "--period-end", "month-end"], obj=session_factory)

    assert result.exit_code == 2
    assert "No such option" in result.output


def test_the_history_reads_the_list_without_recording_anything(session_factory, monkeypatch) -> None:
    _pin_today(monkeypatch, date(2026, 11, 20))
    runner = _ledger(session_factory)
    with session_factory() as session:
        before = session.scalar(select(func.count()).select_from(OperationGroup)), session.scalar(
            select(func.count()).select_from(Operation)
        )

    assert _history(runner, session_factory, "--from", "2026-10-01").exit_code == 0

    with session_factory() as session:
        assert (
            session.scalar(select(func.count()).select_from(OperationGroup)),
            session.scalar(select(func.count()).select_from(Operation)),
        ) == before


@pytest.mark.skip(reason="scaffold: not implemented yet")
def test_failed_set_leaves_operations_unchanged() -> None:
    # TODO(065): invalid list exits 1, names the bad part and choices, operations count and list output unchanged; one sample row per month for workday 25 and last day
    raise NotImplementedError
