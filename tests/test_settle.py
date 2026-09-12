"""Layer 1 — pure unit tests, no fixture.

The debt-simplification netting function `settle` (issue 023). Every decision
in dev/design/expense-splitting.md §8.1 — the greedy max-payer/max-receiver
pairing, the tie-break, the participant set including the user as `None` —
lives in this one pure function and none of it touches a session.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 023")
def test_settle() -> None:
    # TODO(023) — one test per site:
    #   - the spec's acceptance case: Alice +50, Bob -50, you 0 -> one
    #     transfer, not two or three
    #   - the star case: two people both owing you, nothing cancels through a
    #     third party -> two transfers, nothing to simplify
    #   - a chain: Alice +50, Bob -30, Carol -20 -> two transfers, not three
    #   - equal-amount ties resolve identically across repeated runs (the
    #     (-amount, name or "") ordering key, §8.1)
    #   - an all-zero input returns no transfers
    #   - invariant: applying the emitted transfers to the input drives every
    #     position to exactly zero
    raise NotImplementedError
