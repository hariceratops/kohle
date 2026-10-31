"""Layer 1 — pure unit tests for the period builder and spending attribution.

Design §16.2. Worked examples are the spec's Testable list, with its numbers.
"""

import pytest


@pytest.mark.skip(reason="TODO: slice 076 — periods, net spending, partial day N of M")
def test_placeholder_periods() -> None:
    # TODO: 300 on `day 1` from 2026-01-01 yields January, February, ...
    ...


@pytest.mark.skip(reason="TODO: slice 078 — cut at D, identical entry does not cut")
def test_placeholder_cut_at_effective_date() -> None:
    # TODO: 03-01..03-09 (short, 300) and 03-10..03-31 (short, 400), April full
    ...


@pytest.mark.skip(reason="TODO: slice 080 — covered / uncapped / unclassified split")
def test_placeholder_attribution() -> None:
    # TODO: child of capped parent counts toward the parent, not the uncapped row
    ...
