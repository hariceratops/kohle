"""Layer 2 — use case against `session`.

`latest_close` (issue 032), design §8.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 032")
def test_fresh_stale_and_none() -> None:
    # TODO(032) — one test per site:
    #   - a fixture for each of the three outcomes
    #   - stale is distinct from none
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 032")
def test_boundary_day_is_pinned() -> None:
    # TODO(032) — one test per site:
    #   - age 7 is Fresh, age 8 is Stale with the default
    #   - max_age_days=1 moves the boundary
    raise NotImplementedError
