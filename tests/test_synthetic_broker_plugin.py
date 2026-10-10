"""Synthetic broker CSV parser (issue 028)."""

import pytest


def test_parses_buy_sell_and_dividend_rows() -> None:
    # TODO: wrong header; unknown type; malformed decimal; literal NaN; negative quantity on a sell; amount on a buy; quantity on a dividend; unreadable path; each a named error with the right line number. Entry-point discovery: 'kohle-synthetic-broker' in load_plugins() (a failure means run uv sync).
    pytest.skip("scaffold")
