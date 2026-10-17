import pytest
from click.testing import CliRunner

from kohle.app.cli.cli import cli

_SETUP = [
    ["add-account", "Depot", "--type", "asset"],
    ["add-account", "Cash", "--type", "asset"],
    ["add-account", "People", "--type", "asset"],
    ["add-unit", "EUR", "Euro", "--kind", "currency"],
    ["add-unit", "X1", "Thing", "--kind", "security"],
    ["record", "2025-06-01", "buy", "10", "--from", "Cash", "--to", "Depot", "--to-unit", "X1", "--to-price", "100"],
    ["record", "2026-01-05", "buy", "10", "--from", "Cash", "--to", "Depot", "--to-unit", "X1", "--to-price", "120"],
    ["record", "2025-09-01", "sell", "5", "--from", "Depot", "--to", "Cash", "--from-unit", "X1", "--from-price", "130"],
    ["record", "2026-03-10", "sell", "15", "--from", "Depot", "--to", "Cash", "--from-unit", "X1", "--from-price", "130"],
]


def _ledger(session_factory) -> CliRunner:
    runner = CliRunner()
    for args in _SETUP:
        result = runner.invoke(cli, args, obj=session_factory)
        assert result.exit_code == 0, result.output
    return runner


def test_realised_with_and_without_year(session_factory):
    runner = _ledger(session_factory)

    everything = runner.invoke(cli, ["realised"], obj=session_factory)
    only_2026 = runner.invoke(cli, ["realised", "--year", "2026"], obj=session_factory)

    assert everything.exit_code == 0, everything.output
    lines = everything.output.splitlines()
    assert lines[0].split() == ["date", "account", "unit", "quantity", "proceeds", "FIFO", "cost", "gain"]
    assert [row.split()[-1] for row in lines[2:4]] == ["150.00", "250.00"]
    assert lines[-1] == "Realised gain: 400.00"
    assert only_2026.exit_code == 0, only_2026.output
    rows = only_2026.output.splitlines()
    assert [row.split()[-1] for row in rows[2:3]] == ["250.00"]
    assert rows[-1] == "Realised gain: 250.00"
    assert "2025-09-01" not in only_2026.output


def test_realised_without_sales_prints_no_sales_and_zero_total(session_factory):
    runner = CliRunner()
    for args in _SETUP[:5]:
        assert runner.invoke(cli, args, obj=session_factory).exit_code == 0

    result = runner.invoke(cli, ["realised"], obj=session_factory)

    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == ["No sales", "", "Realised gain: 0.00"]


@pytest.mark.skip(reason="issues 041-043")
def test_failures_exit_non_zero_with_no_table():
    ...


@pytest.mark.skip(reason="issue 044")
def test_positions_across_two_depots_with_a_move():
    ...


@pytest.mark.skip(reason="issues 045-046")
def test_net_worth_history_final_row_matches_net_worth():
    ...
