"""Layer 2 — remittance rules, completion and reversal (issues 132-135). Design §18.5."""

import pytest


@pytest.mark.skip(reason="scaffold")
def test_outgoing_remittance_completes_to_a_lot_of_exactly_x() -> None:
    # TODO: §18.5: 1,012.00 EUR with Y=90,000 gives a lot costing exactly 1012.00, FIFO date, incoming realises 88.00 under INR, shortfall writes nothing, uncomplete-remittance both directions, refusals, net worth while pending
    ...
