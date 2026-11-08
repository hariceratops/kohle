"""Layer 1 — valuing holdings quoted in another currency, and subtotals (issues 120, 121, 122, 123). Design §8, §14."""

import pytest


@pytest.mark.skip(reason="TODO scaffold")
def test_market_value_is_quantity_times_close_times_rate() -> None:
    # TODO: each read as the latest on or before the date
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_status_is_the_worse_of_close_and_rate() -> None:
    # TODO: every combination; a stale rate with a fresh close shows the rate's date
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_missing_close_or_rate_falls_back_to_cost() -> None:
    # TODO: marked `no price (at cost)`
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_subtotals_with_a_missing_member_show_a_dash() -> None:
    # TODO: also a zero row and an EUR-only set giving []
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_history_values_each_date_at_its_own_close_and_rate() -> None:
    # TODO: net-worth-history as of each sample date
    raise NotImplementedError
