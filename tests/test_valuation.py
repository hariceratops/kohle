"""Layer 1 — pure unit tests, no fixture.

The valuation rule shared by `balance` and `net-worth` (issues 035, 036). dev/design/market-value-reporting.md §3, §4.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 035")
def test_market_value_per_close_kind() -> None:
    # TODO(035) — one test per site:
    #   - Fresh and Stale give quantity x close
    #   - NoClose gives balance.at_cost (quantity x average cost)
    #   - None on a euro row gives the quantity
    #   - None on a zero-quantity row gives 0
    #   - a negative quantity x close is negative
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 035")
def test_unit_balance_at_cost() -> None:
    # TODO(035) — one test per site:
    #   - a nonzero row
    #   - a None average cost gives 0
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 035")
def test_at_market_totals() -> None:
    # TODO(035) — one test per site:
    #   - a mixed list
    #   - an empty list gives Decimal(0)
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 036")
def test_summarise_counts() -> None:
    # TODO(036) — one test per site:
    #   - mixed list (euro, fresh, stale, no close, a zero row): K, M, S and C asserted
    #   - an empty list gives all zeros
    #   - a euro-only list gives M = 0, balance's 'print neither line' case
    raise NotImplementedError
