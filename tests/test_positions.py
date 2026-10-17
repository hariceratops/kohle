from datetime import date, timedelta
from decimal import Decimal

from click.testing import CliRunner
from sqlalchemy import select

from kohle.app.cli.cli import cli
from kohle.domain.models import Price, Unit

_SETUP = [
    ["add-account", "Depot", "--type", "asset"],
    ["add-account", "Cash", "--type", "asset"],
    ["add-account", "People", "--type", "asset"],
    ["add-unit", "EUR", "Euro", "--kind", "currency"],
    ["add-unit", "FRESH", "Fresh", "--kind", "security"],
    ["add-unit", "NOPRICE", "No price", "--kind", "security"],
    ["record", "2026-01-02", "a", "10", "--from", "Cash", "--to", "Depot", "--to-unit", "FRESH", "--to-price", "5"],
    ["record", "2026-01-03", "b", "10", "--from", "Cash", "--to", "Depot", "--to-unit", "FRESH", "--to-price", "7"],
    ["record", "2026-01-04", "c", "4", "--from", "Cash", "--to", "Depot", "--to-unit", "NOPRICE", "--to-price", "50"],
    ["record", "2026-01-05", "d", "4", "--from", "Depot", "--to", "Cash", "--from-unit", "FRESH", "--from-price", "9"],
]


def _ledger(session_factory) -> CliRunner:
    runner = CliRunner()
    for args in _SETUP:
        result = runner.invoke(cli, args, obj=session_factory)
        assert result.exit_code == 0, result.output
    with session_factory() as session:
        unit_id = session.scalars(select(Unit.id).where(Unit.identifier == "FRESH")).one()
        session.add(
            Price(unit_id=unit_id, price_date=date.today() - timedelta(days=1), price=Decimal(10), source="file")  # noqa: DTZ011
        )
        session.commit()
    return runner


def test_totals_equal_row_sums_and_gain_is_market_value_minus_fifo_cost(session_factory):
    runner = _ledger(session_factory)

    result = runner.invoke(cli, ["positions"], obj=session_factory)

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0].split()[-2:] == ["unrealised", "gain"]
    # FIFO sells 4 of the 10@5, leaving 6@5 and 10@7 = 100.
    fresh = lines[2].split()
    assert fresh[:2] == ["FRESH", "16.00"] and "fresh" in fresh
    assert fresh[-2:] == ["100.00", "60.00"]
    assert lines[-4:] == [
        "Market value: 360.00",
        "FIFO cost: 300.00",
        "Unrealised gain: 60.00",
        "1 of 2 holdings estimated (0 stale, 1 at cost)",
    ]


def test_no_close_row_has_zero_gain_and_is_marked(session_factory):
    runner = _ledger(session_factory)

    result = runner.invoke(cli, ["positions"], obj=session_factory)

    (row,) = [line for line in result.output.splitlines() if line.startswith("NOPRICE")]
    assert "no price (at cost)" in row
    assert row.split()[-2:] == ["200.00", "0.00"]


def test_empty_positions_prints_message_with_zero_totals(session_factory):
    runner = CliRunner()
    for args in _SETUP[:5]:
        assert runner.invoke(cli, args, obj=session_factory).exit_code == 0

    result = runner.invoke(cli, ["positions"], obj=session_factory)

    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        "No positions",
        "",
        "Market value: 0.00",
        "FIFO cost: 0.00",
        "Unrealised gain: 0.00",
        "0 of 0 holdings estimated",
    ]


def test_lot_shortfall_fails_with_no_table(session_factory):
    runner = _ledger(session_factory)
    oversell = ["record", "2026-02-01", "e", "99", "--from", "Depot", "--to", "Cash", "--from-unit", "FRESH", "--from-price", "9"]
    assert runner.invoke(cli, oversell, obj=session_factory).exit_code == 0

    result = runner.invoke(cli, ["positions"], obj=session_factory)

    assert result.exit_code != 0
    assert "FRESH" in result.output and "Unrealised gain" not in result.output
