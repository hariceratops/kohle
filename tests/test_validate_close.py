"""Layer 1 — pure, no database. `validate_close`, design §7."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from kohle.domain.domain_errors import (
    FutureCloseDate,
    NonBaseCurrency,
    NonPositivePrice,
)
from kohle.plugin.price_plugin import Close
from kohle.use_cases.prices import validate_close

TODAY = date(2026, 3, 3)


def _close(price: str = "12", day: date = TODAY, currency: str = "EUR") -> Close:
    return Close(price_date=day, price=Decimal(price), currency=currency)


def test_clean_close_is_accepted_including_today() -> None:
    assert validate_close(_close(), TODAY) is None


@pytest.mark.parametrize("price", ["0", "-1", "NaN", "Infinity", "-Infinity"])
def test_non_positive_or_non_finite_price(price: str) -> None:
    assert isinstance(validate_close(_close(price), TODAY), NonPositivePrice)


def test_future_date() -> None:
    assert isinstance(validate_close(_close(day=TODAY + timedelta(days=1)), TODAY), FutureCloseDate)


@pytest.mark.parametrize("currency", ["USD", "eur"])
def test_non_base_currency_is_compared_exactly(currency: str) -> None:
    rejection = validate_close(_close(currency=currency), TODAY)
    assert isinstance(rejection, NonBaseCurrency)
    assert rejection.base == "EUR"


def test_first_problem_wins() -> None:
    assert isinstance(validate_close(_close("0", TODAY + timedelta(days=1), "USD"), TODAY), NonPositivePrice)
