"""Layer 2 — the nse price plugin through its HTTP seam (issue 110). Design §7, §14."""

import pytest


@pytest.mark.skip(reason="TODO scaffold")
def test_close_for_an_isin_in_the_eq_series() -> None:
    # TODO: reported in INR
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_weekend_and_holiday_walk_back() -> None:
    # TODO: steps back until a file exists
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_ten_weekday_limit() -> None:
    # TODO: gives up after 10 weekdays
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_missing_column_is_an_err() -> None:
    # TODO: never a guess
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_isin_with_only_a_be_row_is_unavailable() -> None:
    # TODO: Unavailable(no_symbol)
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_duplicate_eq_row() -> None:
    # TODO: per the design's rule
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_unreachable_host() -> None:
    # TODO: plugin Err, no network in the test
    raise NotImplementedError
