"""Layer 3 — one smoke scenario through the real CLI (design §16)."""

from datetime import date

import pytest
from click.testing import CliRunner

from kohle.app.cli.cli import cli


def _run(session_factory, *args: str):
    result = CliRunner().invoke(cli, list(args), obj=session_factory)
    assert result.exit_code == 0, result.output
    return result


def _record(session_factory, day: str, amount: str, account: str, refund: bool = False) -> None:
    sides = ("--from", account, "--to", "Cash") if refund else ("--from", "Cash", "--to", account)
    _run(session_factory, "record", day, "x", amount, *sides)


@pytest.fixture
def today(monkeypatch: pytest.MonkeyPatch) -> None:
    class PinnedDate(date):
        @classmethod
        def today(cls) -> "PinnedDate":
            return cls(2026, 3, 20)

    monkeypatch.setattr("kohle.app.cli.cli.date", PinnedDate)


def test_budget_table_with_parent_and_child_caps_a_mid_period_change_and_both_summary_rows(
    session_factory, today
) -> None:
    for args in (
        ["add-account", "People", "--type", "asset"],
        ["add-account", "Unclassified Expense"],
        ["add-account", "Cash", "--type", "asset"],
        ["add-account", "Food"],
        ["add-account", "Bakery", "--parent", "Food"],
        ["add-account", "Dairy", "--parent", "Food"],
        ["add-account", "Hobby"],
        ["add-account", "Anna", "--parent", "People"],
    ):
        _run(session_factory, *args)
    _run(session_factory, "set-cap", "Food", "300", "day 1", "--from", "2026-01-01")
    _run(session_factory, "set-cap", "Food", "400", "day 1", "--from", "2026-03-10")
    _run(session_factory, "set-cap", "Bakery", "50", "day 1", "--from", "2026-01-01")
    _record(session_factory, "2026-01-05", "100", "Bakery")
    _record(session_factory, "2026-01-09", "30", "Bakery", refund=True)
    _record(session_factory, "2026-02-10", "250", "Dairy")
    _record(session_factory, "2026-03-12", "20", "Dairy")
    _record(session_factory, "2026-02-11", "84", "Unclassified Expense")
    _record(session_factory, "2026-02-12", "61", "Hobby")
    _record(session_factory, "2026-02-13", "500", "Anna")

    result = _run(session_factory, "budget")

    rows = [line.split() for line in result.output.splitlines()[2:]]
    assert rows == [
        ["Bakery", "2026-01-01", "2026-01-31", "50.00", "70.00", "20.00", "over"],
        ["Bakery", "2026-02-01", "2026-02-28", "50.00", "0.00", "-50.00", "-"],
        ["Bakery", "2026-03-01", "2026-03-31", "50.00", "0.00", "-50.00", "partial", "day", "20", "of", "31"],
        ["Food", "2026-01-01", "2026-01-31", "300.00", "70.00", "-230.00", "-"],
        ["Food", "2026-02-01", "2026-02-28", "300.00", "250.00", "-50.00", "-"],
        ["Food", "2026-03-01", "2026-03-09", "300.00", "0.00", "-300.00", "short"],
        ["Food", "2026-03-10", "2026-03-31", "400.00", "20.00", "-380.00", "short,", "partial", "day", "11", "of", "22"],
        ["Unclassified", "Expense", "2026-01-01", "2026-03-20", "-", "84.00", "-", "-"],
        ["(uncapped)", "2026-01-01", "2026-03-20", "-", "61.00", "-", "-"],
    ]
