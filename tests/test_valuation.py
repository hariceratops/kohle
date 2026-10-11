"""Layer 1 — pure unit tests, no fixture.

The valuation rule shared by `balance` and `net-worth` (issues 035, 036). dev/design/market-value-reporting.md §3, §4.
"""

from datetime import date
from decimal import Decimal

import pytest

from kohle.domain.models import Price
from kohle.use_cases.journal import UnitBalance
from kohle.use_cases.prices import Fresh, NoClose, Stale
from kohle.use_cases.reporting import ValuedBalance, at_market


def _balance(identifier: str, quantity: str, average_cost: str | None) -> UnitBalance:
    return UnitBalance(identifier, Decimal(quantity), None if average_cost is None else Decimal(average_cost), 1)


def _close(price: str) -> Price:
    return Price(unit_id=1, price_date=date(2026, 3, 1), price=Decimal(price), source="file")


@pytest.mark.parametrize("kind", [Fresh, Stale])
def test_market_value_of_a_close_is_quantity_times_price(kind: type[Fresh] | type[Stale]) -> None:
    row = ValuedBalance(_balance("ISIN", "3", "10"), kind(_close("12.5")))
    assert row.market_value == Decimal("37.5")


def test_market_value_without_a_close_is_quantity_times_average_cost() -> None:
    row = ValuedBalance(_balance("ISIN", "3", "10"), NoClose())
    assert row.market_value == Decimal(30)


def test_market_value_of_a_euro_row_is_its_quantity() -> None:
    assert ValuedBalance(_balance("EUR", "250", "1"), None).market_value == Decimal(250)


def test_market_value_of_a_zero_quantity_row_is_zero() -> None:
    assert ValuedBalance(_balance("ISIN", "0", None), None).market_value == Decimal(0)


def test_market_value_of_a_negative_quantity_is_negative() -> None:
    row = ValuedBalance(_balance("ISIN", "-2", "10"), Fresh(_close("12")))
    assert row.market_value == Decimal(-24)


def test_unit_balance_at_cost() -> None:
    assert _balance("ISIN", "4", "2.5").at_cost == Decimal(10)
    assert _balance("ISIN", "0", None).at_cost == Decimal(0)


def test_at_market_totals() -> None:
    rows = [
        ValuedBalance(_balance("EUR", "100", "1"), None),
        ValuedBalance(_balance("A", "2", "10"), Fresh(_close("15"))),
        ValuedBalance(_balance("B", "1", "7"), NoClose()),
        ValuedBalance(_balance("C", "0", None), None),
    ]
    assert at_market(rows) == Decimal(137)
    assert at_market([]) == Decimal(0)


@pytest.mark.skip(reason="scaffold: issue 036")
def test_summarise_counts() -> None:
    # TODO(036) — one test per site:
    #   - mixed list (euro, fresh, stale, no close, a zero row): K, M, S and C asserted
    #   - an empty list gives all zeros
    #   - a euro-only list gives M = 0, balance's 'print neither line' case
    raise NotImplementedError
