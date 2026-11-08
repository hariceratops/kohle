"""Layer 2 — recording forms for currency units (issues 111, 112, 114, 116, 119). Design §6, §14."""

import pytest


@pytest.mark.skip(reason="TODO scaffold")
def test_record_total_stores_cost() -> None:
    # TODO: --total on a remittance
    raise NotImplementedError


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
