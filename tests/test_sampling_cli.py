"""Layer 3 — set/list-sampling-rules, move-state, list-states, net-worth-history --role (issues 065, 068-070). Design §18.7."""

from datetime import date

import pytest
from click.testing import CliRunner
from sqlalchemy import func, select

from kohle.app.cli.cli import cli
from kohle.domain.models import Operation, OperationGroup, Price, SamplingRuleList
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


def _counts(session_factory) -> tuple[int, int, int]:
    with session_factory() as session:
        return tuple(  # type: ignore[return-value]
            session.scalar(select(func.count()).select_from(model)) for model in (OperationGroup, Operation, Price)
        )


def _set(runner: CliRunner, session_factory, rules: str):
    return runner.invoke(cli, ["set-sampling-rules", rules], obj=session_factory)


def _list(runner: CliRunner, session_factory) -> str:
    result = runner.invoke(cli, ["list-sampling-rules"], obj=session_factory)
    assert result.exit_code == 0, result.output
    return result.output


def test_list_sampling_rules_prints_exactly_the_canonical_line_and_records_nothing(session_factory) -> None:
    runner = CliRunner()
    before = _counts(session_factory)

    assert _list(runner, session_factory) == "mid-month: day 15; salary: last workday\n"
    assert _counts(session_factory) == before


@pytest.mark.parametrize(
    ("rules", "bad_part", "choice"),
    [
        ("salary: day 32", "day 32'", "day N with N from 1 to 31"),
        ("salary: every 2 weeks from 2026-01-02", "every 2 weeks", "last day"),
        ("pay: day 15", "'pay'", "mid-month, salary"),
        ("day 15", "'day 15'", "mid-month or salary"),
        ("", "no sampling rules", "mid-month, salary"),
        (";", "no sampling rules", "mid-month, salary"),
        ("mid-month: day 15; salary: last friday", "last friday", "last workday or last day"),
    ],
)
def test_a_failed_set_names_the_bad_part_and_changes_nothing(session_factory, rules, bad_part, choice) -> None:
    runner = CliRunner()
    listed, before = _list(runner, session_factory), _counts(session_factory)

    result = _set(runner, session_factory, rules)

    assert result.exit_code == 1
    assert bad_part in result.output
    assert choice in result.output
    assert _list(runner, session_factory) == listed
    assert _counts(session_factory) == before


def test_set_replaces_the_list_in_canonical_form_as_one_audited_create(session_factory) -> None:
    runner = CliRunner()
    before = _counts(session_factory)

    result = _set(runner, session_factory, "salary:last  day ; mid-month: day 05;")

    assert result.exit_code == 0, result.output
    assert result.output == "Set sampling rules to salary: last day; mid-month: day 5\n"
    assert _list(runner, session_factory) == "salary: last day; mid-month: day 5\n"
    with session_factory() as session:
        row = session.scalars(select(SamplingRuleList).order_by(SamplingRuleList.id.desc())).first()
        op = session.scalars(select(Operation).order_by(Operation.id.desc())).first()
        assert (op.action, op.entity_type, op.entity_id) == ("create", "sampling_rule_lists", row.id)
    assert _counts(session_factory)[:2] == (before[0] + 1, before[1] + 1)


def test_an_identical_set_adds_no_group(session_factory) -> None:
    runner = CliRunner()
    assert _set(runner, session_factory, "salary: last day").exit_code == 0
    before = _counts(session_factory)

    result = _set(runner, session_factory, "salary: last day")

    assert result.exit_code == 0
    assert _counts(session_factory) == before


def test_a_role_may_repeat(session_factory) -> None:
    runner = CliRunner()

    assert _set(runner, session_factory, "salary: last workday; salary: day 15").exit_code == 0
    assert _list(runner, session_factory) == "salary: last workday; salary: day 15\n"


def test_listing_leaves_no_group_after_a_set(session_factory) -> None:
    runner = CliRunner()
    assert _set(runner, session_factory, "salary: last day").exit_code == 0
    before = _counts(session_factory)

    _list(runner, session_factory)

    assert _counts(session_factory) == before


def _sample_months(output: str) -> list[str]:
    return [ln.split()[0][:7] for ln in output.splitlines()[2:]]


@pytest.mark.parametrize(
    ("rules", "to", "last_row_is_to"),
    [("salary: day 25", "2026-10-31", True), ("salary: last day", "2026-10-31", False)],
)
def test_one_sample_row_per_month_plus_the_to_row(session_factory, monkeypatch, rules, to, last_row_is_to) -> None:
    _pin_today(monkeypatch, date(2026, 11, 20))
    runner = _ledger(session_factory)
    assert _set(runner, session_factory, rules).exit_code == 0

    result = _history(runner, session_factory, "--from", "2026-01-01", "--to", to)

    assert result.exit_code == 0, result.output
    months = _sample_months(result.output)
    samples = months[:-1] if last_row_is_to else months
    assert samples == [f"2026-{m:02d}" for m in range(1, 11)]
    if last_row_is_to:
        assert result.output.splitlines()[-1].split()[0] == to
        assert result.output.splitlines()[-1].split()[-1] == "-"


def test_set_and_list_never_touch_prices_or_plugins(session_factory, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("no price plugin may load")

    monkeypatch.setattr("kohle.app.cli.cli.load_price_plugins", boom)
    runner = CliRunner()
    before = _counts(session_factory)[2]

    assert _set(runner, session_factory, "salary: last day").exit_code == 0
    _list(runner, session_factory)

    assert _counts(session_factory)[2] == before
