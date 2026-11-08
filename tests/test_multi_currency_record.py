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


def _expense_ledger(session_factory) -> None:
    _purchase_ledger(session_factory)
    for args in (
        ["add-account", "Groceries", "--type", "expense"],
        ["set-cap", "Groceries", "2000", "day 1", "--from", "2026-01-01"],
    ):
        result = _run(session_factory, *args)
        assert result.exit_code == 0, result.output


def test_record_currency_builds_at_par_lines(session_factory) -> None:
    _expense_ledger(session_factory)

    result = _run(
        session_factory, "record", "2026-03-10", "Groceries", "95000",
        "--from", "IndianBank", "--to", "Groceries", "--currency", "INR",
    )

    assert result.exit_code == 0, result.output
    assert result.output == "Recorded 95000 INR: credited IndianBank, debited Groceries\n"
    with session_factory() as session:
        lines = list(session.scalars(select(JournalLine).where(JournalLine.entry_id == 3)))
        assert len(lines) == 2
        for line in lines:
            assert (line.unit.identifier, line.quantity, line.unit_price, line.cost) == ("INR", Decimal(95000), Decimal(1), None)
            assert line.price_unit.identifier == "INR"
        assert {line.account.name: line.is_debit for line in lines} == {"IndianBank": False, "Groceries": True}


@pytest.mark.parametrize(
    "extra",
    [["--currency", "EUR"], ["--currency", "INR", "--total", "5"]],
)
def test_currency_without_a_unit_misuse_is_a_flag_error(session_factory, extra) -> None:
    _expense_ledger(session_factory)

    result = _run(session_factory, "record", "2026-03-10", "Groceries", "100", "--from", "IndianBank", "--to", "Groceries", *extra)

    assert result.exit_code == 2


def test_an_at_par_currency_must_be_a_currency_unit(session_factory) -> None:
    _expense_ledger(session_factory)

    result = _run(
        session_factory, "record", "2026-03-10", "Groceries", "10",
        "--from", "IndianBank", "--to", "Groceries", "--currency", "INFY",
    )

    assert result.exit_code == 1
    assert "INFY (security) cannot be a price currency" in result.output


def test_inr_expense_is_valued_at_lot_cost(session_factory) -> None:
    _expense_ledger(session_factory)
    _run(session_factory, "record", "2026-03-10", "Groceries", "95000", "--from", "IndianBank", "--to", "Groceries", "--currency", "INR")

    positions = {p.holding.unit_identifier: p.holding for p in QueryPositions(session_factory()).execute(date(2026, 3, 11), 7).unwrap().positions}
    budget = _run(session_factory, "budget", "--from", "2026-03-01", "--to", "2026-03-31")

    assert (positions["INR"].quantity, positions["INR"].fifo_cost) == (Decimal(95000), Decimal(1045))
    assert QueryRealised(session_factory()).execute(None).unwrap() == []
    assert budget.exit_code == 0, budget.output
    row = next(line.split() for line in budget.output.splitlines() if line.startswith("Groceries"))
    assert "1055.00" in row, budget.output


def test_entries_in_period_shows_face_values_and_the_currency_priced_in(session_factory) -> None:
    _expense_ledger(session_factory)
    _run(session_factory, "record", "2026-03-10", "Groceries", "95000", "--from", "IndianBank", "--to", "Groceries", "--currency", "INR")
    _run(session_factory, "record", "2026-03-11", "Corner shop", "80", "--from", "Girokonto", "--to", "Groceries")

    mixed = _run(session_factory, "entries-in-period", "Groceries", "2026-03-01", "2026-04-01")
    euro_only = _run(session_factory, "entries-in-period", "Girokonto", "2026-03-01", "2026-04-01")

    assert mixed.exit_code == 0, mixed.output
    header, _, inr, eur = mixed.output.splitlines()
    assert header.split()[-3:] == ["value", "priced", "in"]
    assert inr.split()[-3:] == ["INR", "95000.00", "INR"]
    assert eur.split()[-3:] == ["EUR", "80.00", "EUR"]
    assert "priced in" not in euro_only.output


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


def _sale_ledger(session_factory) -> None:
    for args in (
        ["add-account", "People", "--type", "asset"],
        ["add-account", "Girokonto", "--type", "asset"],
        ["add-account", "Demat", "--type", "asset"],
        ["add-account", "DematCash", "--type", "asset"],
        ["add-account", "Dividends", "--type", "income"],
        ["add-unit", "INR", "Indian rupee", "--kind", "currency"],
        ["add-unit", "INFY", "Infosys", "--kind", "security"],
        ["record", "2026-03-01", "Buy INFY", "50", "--from", "Girokonto", "--to", "Demat", "--to-unit", "INFY", "--to-price", "12"],
    ):
        result = _run(session_factory, *args)
        assert result.exit_code == 0, result.output


def test_selling_a_stock_for_a_currency_realises_the_gain_at_the_rate(session_factory) -> None:
    _sale_ledger(session_factory)

    result = _run(
        session_factory, "record", "2026-03-10", "Sell INFY", "50",
        "--from", "Demat", "--to", "DematCash", "--from-unit", "INFY", "--from-price", "1300",
        "--currency", "INR", "--rate", "0.0104",
    )

    assert result.exit_code == 0, result.output
    assert result.output == "Recorded 50 INFY @ 1300 INR at 0.0104 EUR: credited Demat, debited DematCash\n"
    with session_factory() as session:
        lines = list(session.scalars(select(JournalLine).where(JournalLine.entry_id == 2)))
        stock = next(line for line in lines if line.unit.identifier == "INFY")
        inr = next(line for line in lines if line.unit.identifier == "INR")
        assert (stock.quantity, stock.cost, stock.is_debit) == (Decimal(50), Decimal(676), False)
        assert (inr.quantity, inr.unit_price, inr.cost, inr.is_debit) == (Decimal(65000), Decimal("0.0104"), Decimal(676), True)
        assert stock.price_unit is None and inr.price_unit is None

    sales = QueryRealised(session_factory()).execute(None).unwrap()
    assert [(s.unit_identifier, s.quantity, s.proceeds, s.fifo_cost, s.gain) for s in sales] == [
        ("INFY", Decimal(50), Decimal(676), Decimal(600), Decimal(76)),
    ]
    positions = {p.holding.unit_identifier: p.holding for p in QueryPositions(session_factory()).execute(date(2026, 3, 11), 7).unwrap().positions}
    assert (positions["INR"].quantity, positions["INR"].fifo_cost) == (Decimal(65000), Decimal(676))


def test_a_dividend_in_a_currency_becomes_a_lot_at_the_rate(session_factory) -> None:
    _sale_ledger(session_factory)

    result = _run(
        session_factory, "record", "2026-03-10", "Dividend", "2000",
        "--from", "Dividends", "--to", "DematCash", "--currency", "INR", "--rate", "0.0104",
    )

    assert result.exit_code == 0, result.output
    assert result.output == "Recorded 2000 INR at 0.0104 EUR: credited Dividends, debited DematCash\n"
    positions = {p.holding.unit_identifier: p.holding for p in QueryPositions(session_factory()).execute(date(2026, 3, 11), 7).unwrap().positions}
    assert (positions["INR"].quantity, positions["INR"].fifo_cost) == (Decimal(2000), Decimal("20.8"))


def test_inflow_without_a_rate_writes_nothing(session_factory) -> None:
    _sale_ledger(session_factory)

    dividend = _run(
        session_factory, "record", "2026-03-10", "Dividend", "2000",
        "--from", "Dividends", "--to", "DematCash", "--currency", "INR",
    )
    sale = _run(
        session_factory, "record", "2026-03-10", "Sell INFY", "50",
        "--from", "Demat", "--to", "DematCash", "--from-unit", "INFY", "--from-price", "1300", "--currency", "INR",
    )

    assert dividend.exit_code == 1
    assert dividend.output == (
        "Error: 'Dividends' is credited in INR with no euro value; currency arriving needs a rate (record --rate)\n"
    )
    assert sale.exit_code == 2
    assert "--rate" in sale.output
    with session_factory() as session:
        assert [line.entry_id for line in session.scalars(select(JournalLine))] == [1, 1]


def test_rate_is_euros_per_unit_and_quantised(session_factory) -> None:
    _sale_ledger(session_factory)

    result = _run(
        session_factory, "record", "2026-03-10", "Dividend", "3",
        "--from", "Dividends", "--to", "DematCash", "--currency", "INR", "--rate", "0.123456789",
    )

    assert result.exit_code == 0, result.output
    with session_factory() as session:
        inr = next(line for line in session.scalars(select(JournalLine)) if line.unit.identifier == "INR" and line.is_debit)
        assert (inr.unit_price, inr.cost) == (Decimal("0.12345679"), Decimal("0.37037037"))


@pytest.mark.parametrize(
    "extra",
    [
        ["--rate", "0.0104"],
        ["--currency", "INR", "--rate", "0.0104", "--to-unit", "INFY", "--to-price", "1"],
        ["--currency", "INR", "--rate", "0"],
    ],
)
def test_rate_misuse_is_a_usage_error(session_factory, extra: list[str]) -> None:
    _sale_ledger(session_factory)

    result = _run(
        session_factory, "record", "2026-03-10", "Dividend", "2000", "--from", "Dividends", "--to", "DematCash", *extra
    )

    assert result.exit_code == 2, result.output


@pytest.mark.skip(reason="TODO scaffold")
def test_record_split_expresses_the_same_entries() -> None:
    # TODO: =T total and the sixth currency field
    raise NotImplementedError


def test_changing_a_currency_back_into_euros_realises_the_fx_gain(session_factory) -> None:
    _purchase_ledger(session_factory)
    _run(
        session_factory, "record", "2026-03-10", "Buy INFY", "100",
        "--from", "IndianBank", "--to", "Demat", "--to-unit", "INFY", "--to-price", "1200", "--currency", "INR",
    )

    result = _run(
        session_factory, "record", "2026-03-20", "Back to euros", "70000",
        "--from", "IndianBank", "--to", "Girokonto", "--from-unit", "INR", "--total", "800",
    )

    assert result.exit_code == 0, result.output
    assert result.output == "Recorded 70000 INR for 800 EUR: credited IndianBank, debited Girokonto\n"
    with session_factory() as session:
        lines = list(session.scalars(select(JournalLine).where(JournalLine.entry_id == 4)))
        inr = next(line for line in lines if line.unit.identifier == "INR")
        eur = next(line for line in lines if line.unit.identifier == "EUR")
        assert (inr.quantity, inr.cost, inr.is_debit) == (Decimal(70000), Decimal(800), False)
        assert (eur.quantity, eur.unit_price, eur.is_debit) == (Decimal(800), Decimal(1), True)

    sales = QueryRealised(session_factory()).execute(None).unwrap()
    assert [(s.unit_identifier, s.quantity, s.proceeds, s.fifo_cost, s.gain) for s in sales] == [
        ("INR", Decimal(70000), Decimal(800), Decimal(770), Decimal(30))
    ]
    realised = _run(session_factory, "realised")
    assert realised.exit_code == 0, realised.output
    assert "INR" in realised.output
    assert "Realised gain: 30.00" in realised.output


def test_changing_more_currency_than_the_lots_hold_fails_the_reports(session_factory) -> None:
    _purchase_ledger(session_factory)

    result = _run(
        session_factory, "record", "2026-03-20", "Back to euros", "200000",
        "--from", "IndianBank", "--to", "Girokonto", "--from-unit", "INR", "--total", "2300",
    )

    assert result.exit_code == 0, result.output
    realised = _run(session_factory, "realised")
    assert realised.exit_code == 1
    assert "INR in 'IndianBank' on 2026-03-20: disposes of 10000 more than the account holds" in realised.output


def _move_ledger(session_factory) -> None:
    _purchase_ledger(session_factory)
    for args in (
        ["add-account", "DematCash", "--type", "asset"],
        ["add-account", "Jonas", "--type", "asset", "--parent", "People"],
    ):
        result = _run(session_factory, *args)
        assert result.exit_code == 0, result.output


def test_a_move_between_own_accounts_keeps_the_lots_and_realises_nothing(session_factory) -> None:
    _move_ledger(session_factory)

    moved = _run(
        session_factory, "record", "2026-03-10", "To demat", "95000",
        "--from", "IndianBank", "--to", "DematCash", "--currency", "INR",
    )
    bought = _run(
        session_factory, "record", "2026-03-11", "Buy INFY", "100",
        "--from", "DematCash", "--to", "Demat", "--to-unit", "INFY", "--to-price", "900", "--currency", "INR",
    )

    assert moved.exit_code == 0, moved.output
    assert bought.exit_code == 0, bought.output
    assert QueryRealised(session_factory()).execute(None).unwrap() == []
    positions = {
        p.holding.unit_identifier: p.holding
        for p in QueryPositions(session_factory()).execute(date(2026, 3, 12), 7).unwrap().positions
    }
    # The oldest lot, 90,000 at 1,000, crossed to DematCash with its cost and paid for the shares.
    assert (positions["INR"].quantity, positions["INR"].fifo_cost) == (Decimal(100000), Decimal(1100))
    assert positions["INFY"].fifo_cost == Decimal(1000)


@pytest.mark.parametrize("direction", [["--from", "IndianBank", "--to", "Jonas"], ["--from", "Jonas", "--to", "IndianBank"]])
def test_a_currency_moved_to_or_from_people_fails_the_reports(session_factory, direction: list[str]) -> None:
    _move_ledger(session_factory)
    recorded = _run(session_factory, "record", "2026-03-10", "Lend", "5000", *direction, "--currency", "INR")
    assert recorded.exit_code == 0, recorded.output

    for command in (["positions"], ["realised"], ["balance", "IndianBank"], ["net-worth"]):
        result = _run(session_factory, *command)
        assert result.exit_code == 1, command
        assert "puts INR on People account 'Jonas'; currencies other than EUR cannot be owed by people" in result.output
