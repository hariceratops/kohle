"""Layer 2 — recording forms for currency units (issues 111, 112, 114, 116, 119). Design §6, §14."""

from datetime import date
from decimal import Decimal

import pytest
from click.testing import CliRunner
from sqlalchemy import select

from kohle.app.cli.cli import cli
from kohle.domain.models import JournalLine
from kohle.use_cases.lots import QueryRealised


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


@pytest.mark.skip(reason="TODO scaffold")
def test_record_currency_builds_at_par_lines() -> None:
    # TODO: --currency
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_opening_entry_for_a_currency_and_a_security() -> None:
    # TODO: from a named opening account
    raise NotImplementedError


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
