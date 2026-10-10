"""ImportStatement security branch (issue 027)."""

import pytest


def test_buy_and_sell_post_balanced_transfers() -> None:
    # TODO: buy/sell lines; classifications count equals cash row count; unknown instruments all named in one error; currency unit gives NotASecurityUnit; MissingInstrumentAccount; AccountNotFoundError; PostingToNonLeafAccount; SecurityRow(unit_price=None) as last row rejected with nothing written; re-import under a different instrument account posts nothing.
    pytest.skip("scaffold")
