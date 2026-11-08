"""Layer 1 — the cost fold and entry balancing for currency lines (issues 111, 113). Design §2, §14."""

import pytest


@pytest.mark.skip(reason="TODO scaffold")
def test_fold_is_fifo_for_a_currency() -> None:
    # TODO: total 2,100, not 2,103.68
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_fold_without_costs_is_unchanged() -> None:
    # TODO: identical to today's moving average
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_validate_lines_balances_per_price_currency() -> None:
    # TODO: V1 and V3-V6, one case each
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_base_currency_imbalance_keeps_todays_message() -> None:
    # TODO: a plain euro entry gets exactly today's check and text
    raise NotImplementedError
