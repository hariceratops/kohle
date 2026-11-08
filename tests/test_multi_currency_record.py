"""Layer 2 — recording forms for currency units (issues 111, 112, 114, 116, 119). Design §6, §14."""

from datetime import date
from decimal import Decimal

import pytest
from click.testing import CliRunner
from sqlalchemy import select

from kohle.app.cli.cli import cli
from kohle.domain.models import JournalLine
from kohle.use_cases.lots import QueryRealised
from kohle.use_cases.reporting import QueryPositions


def _run(session_factory, *args: str):
    return CliRunner().invoke(cli, list(args), obj=session_factory)


def _remittance_ledger(session_factory) -> None:
    for args in (
        ["add-account", "People", "--type", "asset"],
        ["add-account", "Girokonto", "--type", "asset"],
        ["add-account", "IndianBank", "--type", "asset"],
        ["add-unit", "INR", "Indian rupee", "--kind", "currency"],
    ):
        result = _run(session_factory, *args)
        assert result.exit_code == 0, result.output


def test_record_total_stores_cost(session_factory) -> None:
    _remittance_ledger(session_factory)

    result = _run(
        session_factory, "record", "2026-03-05", "Remittance", "90000",
        "--from", "Girokonto", "--to", "IndianBank", "--to-unit", "INR", "--total", "1000",
    )

    assert result.exit_code == 0, result.output
    assert result.output == "Recorded 90000 INR for 1000 EUR: credited Girokonto, debited IndianBank\n"
    with session_factory() as session:
        lines = {line.unit.identifier: line for line in session.scalars(select(JournalLine))}
    assert (lines["INR"].quantity, lines["INR"].cost, lines["INR"].is_debit) == (Decimal(90000), Decimal(1000), True)
    assert lines["INR"].unit_price == Decimal("0.01111111")
    assert (lines["EUR"].quantity, lines["EUR"].unit_price, lines["EUR"].cost) == (Decimal(1000), Decimal(1), None)

    balance = _run(session_factory, "balance", "IndianBank")
    assert balance.exit_code == 0, balance.output
    assert balance.output.splitlines()[2].split()[:2] == ["INR", "90000.00"]

    assert QueryRealised(session_factory()).execute(None).unwrap() == []


@pytest.mark.parametrize(
    "extra",
    [
        ["--total", "1000"],
        ["--to-unit", "INR", "--to-price", "1", "--total", "1000"],
        ["--to-unit", "INR", "--total", "0"],
    ],
)
def test_total_without_a_unit_or_with_a_price_or_non_positive_is_a_flag_error(session_factory, extra) -> None:
    _remittance_ledger(session_factory)

    result = _run(
        session_factory, "record", "2026-03-05", "Remittance", "90000",
        "--from", "Girokonto", "--to", "IndianBank", *extra,
    )

    assert result.exit_code == 2


def _purchase_ledger(session_factory) -> None:
    _remittance_ledger(session_factory)
    for args in (
        ["add-account", "Demat", "--type", "asset"],
        ["add-unit", "INFY", "Infosys", "--kind", "security"],
        ["record", "2026-03-05", "Remittance", "90000", "--from", "Girokonto", "--to", "IndianBank", "--to-unit", "INR", "--total", "1000"],
        ["record", "2026-03-06", "Remittance", "100000", "--from", "Girokonto", "--to", "IndianBank", "--to-unit", "INR", "--total", "1100"],
    ):
        result = _run(session_factory, *args)
        assert result.exit_code == 0, result.output


def test_buying_a_security_with_a_currency_costs_the_lots_used(session_factory) -> None:
    _purchase_ledger(session_factory)

    result = _run(
        session_factory, "record", "2026-03-10", "Buy INFY", "100",
        "--from", "IndianBank", "--to", "Demat", "--to-unit", "INFY", "--to-price", "1200", "--currency", "INR",
    )

    assert result.exit_code == 0, result.output
    assert result.output == "Recorded 100 INFY @ 1200 INR: credited IndianBank, debited Demat\n"
    with session_factory() as session:
        lines = list(session.scalars(select(JournalLine).where(JournalLine.entry_id == 3)))
        stock = next(line for line in lines if line.unit.identifier == "INFY")
        paid = next(line for line in lines if line.unit.identifier == "INR")
        assert (stock.quantity, stock.unit_price, stock.cost, stock.is_debit) == (Decimal(100), Decimal(1200), Decimal(120000), True)
        assert (paid.quantity, paid.unit_price, paid.cost, paid.is_debit) == (Decimal(120000), Decimal(1), None, False)
        assert stock.price_unit.identifier == paid.price_unit.identifier == "INR"

    positions = {p.holding.unit_identifier: p.holding for p in QueryPositions(session_factory()).execute(date(2026, 3, 11), 7).unwrap().positions}
    assert (positions["INFY"].quantity, positions["INFY"].fifo_cost) == (Decimal(100), Decimal(1330))
    assert (positions["INR"].quantity, positions["INR"].fifo_cost) == (Decimal(70000), Decimal(770))
    assert QueryRealised(session_factory()).execute(None).unwrap() == []

    for account, unit, at_cost in (("Demat", "INFY", "1330.00"), ("IndianBank", "INR", "770.00")):
        balance = _run(session_factory, "balance", account)
        assert balance.exit_code == 0, balance.output
        row = next(line.split() for line in balance.output.splitlines() if line.startswith(unit))
        assert row[4] == at_cost, balance.output


def test_a_total_in_a_currency_is_stored_as_the_cost(session_factory) -> None:
    _purchase_ledger(session_factory)

    result = _run(
        session_factory, "record", "2026-03-10", "Buy INFY", "100",
        "--from", "IndianBank", "--to", "Demat", "--to-unit", "INFY", "--total", "120450", "--currency", "INR",
    )

    assert result.output == "Recorded 100 INFY for 120450 INR: credited IndianBank, debited Demat\n"
    with session_factory() as session:
        stock = session.scalars(select(JournalLine).where(JournalLine.entry_id == 3)).all()
        cost = {line.unit.identifier: line.cost for line in stock}
        assert cost["INFY"] == Decimal(120450)
        assert next(line.quantity for line in stock if line.unit.identifier == "INR") == Decimal(120450)


@pytest.mark.parametrize(
    "extra",
    [
        ["--to-unit", "INFY", "--to-price", "1200", "--currency", "EUR"],
        ["--currency", "INR"],
        ["--from-unit", "INFY", "--from-price", "1200", "--currency", "INR"],
        ["--to-unit", "INR", "--to-price", "1", "--currency", "INR"],
    ],
)
def test_currency_flag_misuse_is_a_flag_error(session_factory, extra) -> None:
    _purchase_ledger(session_factory)

    result = _run(
        session_factory, "record", "2026-03-10", "Buy", "100", "--from", "IndianBank", "--to", "Demat", *extra,
    )

    assert result.exit_code == 2


def test_a_security_is_not_a_price_currency(session_factory) -> None:
    _purchase_ledger(session_factory)
    _run(session_factory, "add-unit", "TCS", "Tata", "--kind", "security")

    result = _run(
        session_factory, "record", "2026-03-10", "Buy", "100",
        "--from", "IndianBank", "--to", "Demat", "--to-unit", "INFY", "--to-price", "1200", "--currency", "TCS",
    )

    assert result.exit_code == 1
    assert "TCS (security) cannot be a price currency" in result.output


def test_a_purchase_beyond_the_lots_fails_the_reports(session_factory) -> None:
    _purchase_ledger(session_factory)
    recorded = _run(
        session_factory, "record", "2026-03-10", "Buy INFY", "200",
        "--from", "IndianBank", "--to", "Demat", "--to-unit", "INFY", "--to-price", "1200", "--currency", "INR",
    )
    assert recorded.exit_code == 0, recorded.output

    for command in (["positions"], ["realised"], ["balance", "Demat"], ["net-worth"]):
        result = _run(session_factory, *command)
        assert result.exit_code == 1, command
        assert "INR in 'IndianBank' on 2026-03-10: disposes of 50000 more than the account holds" in result.output


@pytest.mark.skip(reason="TODO scaffold: issue 114")
def test_record_currency_builds_at_par_lines() -> None:
    # TODO: --currency
    raise NotImplementedError


def test_opening_entry_for_a_currency_and_a_security(session_factory) -> None:
    _remittance_ledger(session_factory)
    for args in (
        ["add-account", "Opening", "--type", "income"],
        ["add-account", "Demat", "--type", "asset"],
        ["add-unit", "INFY", "Infosys", "--kind", "security"],
    ):
        assert _run(session_factory, *args).exit_code == 0

    currency = _run(
        session_factory, "record", "2026-01-01", "Opening", "90000",
        "--from", "Opening", "--to", "IndianBank", "--to-unit", "INR", "--total", "1000",
    )
    security = _run(
        session_factory, "record", "2026-01-01", "Opening", "100",
        "--from", "Opening", "--to", "Demat", "--to-unit", "INFY", "--total", "1500",
    )

    assert currency.exit_code == 0, currency.output
    assert security.exit_code == 0, security.output
    assert security.output == "Recorded 100 INFY for 1500 EUR: credited Opening, debited Demat\n"
    with session_factory() as session:
        lines = list(session.scalars(select(JournalLine)))
        held = {line.unit.identifier: line for line in lines if line.unit.identifier != "EUR"}
        assert (held["INR"].quantity, held["INR"].cost) == (Decimal(90000), Decimal(1000))
        assert (held["INFY"].quantity, held["INFY"].cost) == (Decimal(100), Decimal(1500))
        credits = [line for line in lines if not line.is_debit]
        assert sorted(line.quantity for line in credits) == [Decimal(1000), Decimal(1500)]
        assert all(line.account.name == "Opening" for line in credits)


@pytest.mark.skip(reason="TODO scaffold")
def test_inr_expense_is_valued_at_lot_cost() -> None:
    # TODO: QueryBudget counts it at lot cost, no gain
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_inflow_without_a_rate_writes_nothing() -> None:
    # TODO: CurrencyInflowWithoutRate; a rate-less sale is a flag error, exit 2
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_rate_is_euros_per_unit_and_quantised() -> None:
    # TODO: --rate
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_record_split_expresses_the_same_entries() -> None:
    # TODO: =T total and the sixth currency field
    raise NotImplementedError
