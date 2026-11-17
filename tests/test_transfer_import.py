"""Layer 2 — import-statement end to end for transfers (issues 126-128). Design §18.2-18.3."""

import pytest


@pytest.mark.skip(reason="scaffold")
def test_transfer_counts_once_in_both_import_orders() -> None:
    # TODO: §18.2: the spec scenario in both orders, re-import writes nothing, 3-day vs 4-day window, fall-through first, never-imported counterpart, mirror record, crash leaves ledger and group count unchanged; §18.3: classify-rules preview with both lines
    ...
