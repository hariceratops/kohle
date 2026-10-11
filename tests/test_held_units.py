"""Layer 2 — use case against `session`.

`held_units` in journal.py (issue 030), design §6.2.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 030")
def test_fully_sold_fractional_position_is_not_held() -> None:
    # TODO(030) — one test per site:
    #   - REGRESSION: 0.1 + 0.2 - 0.3 summed in Decimal, not SQL SUM, is not held (SQLite stores these as floats)
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 030")
def test_transfer_between_two_depots_stays_held() -> None:
    # TODO(030) — one test per site:
    #   - net across all accounts, not per account
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 030")
def test_held_units_is_kind_agnostic() -> None:
    # TODO(030) — one test per site:
    #   - EUR is returned; the security filter happens in ListPriceTargets
    raise NotImplementedError
