"""_cross_unit_lines helper (issue 027)."""

import pytest


def test_buy_debits_holding_and_credits_cash() -> None:
    # TODO: buy and sell directions, cash quantity is q*p at price 1; RecordSimpleEntry still produces its old lines after moving onto the helper.
    pytest.skip("scaffold")
