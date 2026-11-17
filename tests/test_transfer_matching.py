"""Layer 1 — pure mirror matching, rule file and replay (issues 126-127, 135). Design §18.1."""

import pytest


@pytest.mark.skip(reason="scaffold")
def test_is_mirror_window_amount_direction_and_iban() -> None:
    # TODO: §18.1: is_mirror table (days -4..+4, exact amount, same sign, IBAN cases), nearest-candidate tie-breaks, match_rule self-counterpart skip, rule-file rejections and round trip, lots.replay with a reversal pair
    ...
