"""Layer 2 — CLI tests over a real SQLite ledger.

Design §16.4: set-cap, end-cap, list-caps, budget.
"""

import pytest
from click.testing import CliRunner
from sqlalchemy import func, select

from kohle.app.cli.cli import cli
from kohle.domain.models import Operation


def _run(session_factory, *args: str):
    return CliRunner().invoke(cli, list(args), obj=session_factory)


def _ledger(session_factory) -> None:
    for args in (
        ["add-account", "People", "--type", "asset"],
        ["add-account", "Unclassified Expense"],
        ["add-account", "Food"],
        ["add-account", "Groceries"],
        ["add-account", "Salary", "--type", "income"],
        ["add-account", "Cash", "--type", "asset"],
        ["add-account", "Card", "--type", "liability"],
        ["add-account", "Anna", "--parent", "People"],
    ):
        result = _run(session_factory, *args)
        assert result.exit_code == 0, result.output


def _operations(session_factory) -> int:
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(Operation))


def test_set_cap_records_entries_and_list_caps_shows_every_history_oldest_first(session_factory) -> None:
    _ledger(session_factory)

    first = _run(session_factory, "set-cap", "Groceries", "400", "day 1", "--from", "2026-03-10")
    second = _run(session_factory, "set-cap", "Groceries", "300", "day  1", "--from", "2026-01-01")
    parent = _run(session_factory, "set-cap", "Food", "0", "yearly 3-1", "--from", "2027-03-01")
    listed = _run(session_factory, "list-caps")

    assert first.output == "Set cap on Groceries from 2026-03-10: 400.00, day 1\n"
    assert second.exit_code == 0 and parent.exit_code == 0, second.output + parent.output
    rows = [line.split(None, 3) for line in listed.output.splitlines()[2:]]
    assert rows == [
        ["Food", "2027-03-01", "0.00", "yearly 03-01"],
        ["Groceries", "2026-01-01", "300.00", "day 1"],
        ["Groceries", "2026-03-10", "400.00", "day 1"],
    ]


def test_set_cap_on_an_existing_date_replaces_the_entry(session_factory) -> None:
    _ledger(session_factory)
    _run(session_factory, "set-cap", "Groceries", "300", "day 1", "--from", "2026-01-01")
    before = _operations(session_factory)

    _run(session_factory, "set-cap", "Groceries", "300", "day 1", "--from", "2026-01-01")
    assert _operations(session_factory) == before, "an identical replay writes nothing"

    _run(session_factory, "set-cap", "Groceries", "350", "day 5", "--from", "2026-01-01")
    listed = _run(session_factory, "list-caps").output.splitlines()[2:]
    assert [line.split(None, 3)[2:] for line in listed] == [["350.00", "day 5"]]
    assert _operations(session_factory) == before + 1


def test_each_successful_set_cap_is_one_audit_operation(session_factory) -> None:
    _ledger(session_factory)
    before = _operations(session_factory)

    _run(session_factory, "set-cap", "Groceries", "300", "day 1", "--from", "2026-01-01")

    assert _operations(session_factory) == before + 1
    with session_factory() as session:
        last = session.scalars(select(Operation).order_by(Operation.id.desc())).first()
        assert (last.entity_type, last.action) == ("cap_entries", "create")


def test_list_caps_with_no_caps_says_how_to_set_one(session_factory) -> None:
    result = _run(session_factory, "list-caps")

    assert result.exit_code == 0
    assert result.output.startswith("No caps; set one with `kohle-cli set-cap")


@pytest.mark.parametrize(
    ("args", "fragments"),
    [
        (["Unclassified Expense", "300", "day 1"], ["it has its own row in budget", "Groceries"]),
        (["Salary", "300", "day 1"], ["it is an income account", "Groceries"]),
        (["Cash", "300", "day 1"], ["it is an asset account"]),
        (["Card", "300", "day 1"], ["it is an liability account"]),
        (["Anna", "300", "day 1"], ["it is a person under People"]),
        (["Nowhere", "300", "day 1"], ["no such account", "Food, Groceries"]),
        (["Groceries", "300", "every 1 year from 2026-01-01"], ["unit"]),
        (["Groceries", "300", "fortnightly"], ["one of:", "last workday"]),
        (["Groceries", "NaN", "day 1"], ["invalid cap amount NaN", "0 or more"]),
    ],
    ids=["unclassified", "income", "asset", "liability", "person", "missing", "bad unit", "bad rule", "nan"],
)
def test_a_refused_set_cap_writes_nothing_and_names_the_bad_part(session_factory, args, fragments) -> None:
    _ledger(session_factory)
    _run(session_factory, "set-cap", "Groceries", "300", "day 1", "--from", "2026-01-01")
    listed, operations = _run(session_factory, "list-caps").output, _operations(session_factory)

    result = _run(session_factory, "set-cap", *args, "--from", "2026-02-01")

    assert result.exit_code == 1, result.output
    for fragment in fragments:
        assert fragment in result.output
    assert _run(session_factory, "list-caps").output == listed
    assert _operations(session_factory) == operations


def test_a_negative_amount_is_refused_and_writes_nothing(session_factory) -> None:
    _ledger(session_factory)
    operations = _operations(session_factory)

    result = _run(session_factory, "set-cap", "--from", "2026-01-01", "Groceries", "--", "-5", "day 1")

    assert result.exit_code == 1
    assert "invalid cap amount -5; expected a number of 0 or more" in result.output
    assert _operations(session_factory) == operations


def test_a_bad_date_is_a_usage_error_that_writes_nothing(session_factory) -> None:
    _ledger(session_factory)
    operations = _operations(session_factory)

    bad = _run(session_factory, "set-cap", "Groceries", "300", "day 1", "--from", "2026-13-01")
    missing = _run(session_factory, "set-cap", "Groceries", "300", "day 1")

    assert bad.exit_code == 2 and missing.exit_code == 2
    assert _operations(session_factory) == operations


def test_caps_are_never_written_to_config_toml(session_factory, tmp_path) -> None:
    _ledger(session_factory)

    _run(session_factory, "set-cap", "Groceries", "300", "day 1", "--from", "2026-01-01")

    assert not (tmp_path / "xdg-config" / "kohle" / "config.toml").exists()


@pytest.mark.skip(reason="TODO: slice 076 — budget report, pure read")
def test_placeholder_budget_report() -> None:
    # TODO: no operations / operation_groups rows added, no price plugin called
    ...


@pytest.mark.skip(reason="TODO: slice 077 — Bundesland refusal for working-day rules")
def test_placeholder_budget_bundesland_refusal() -> None:
    # TODO: refuses with the move-state hint only when a rule shifts to a working day
    ...


@pytest.mark.skip(reason="TODO: slice 079 — end-cap")
def test_placeholder_end_cap() -> None:
    # TODO: end-cap from D; lines dated D or later land in the uncapped row
    ...
