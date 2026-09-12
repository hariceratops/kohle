"""Layer 3 — use-case tests against the `session` fixture.

`NetWorth` (issue 024), living in `kohle/use_cases/journal.py` beside
`QueryAccountBalance` (design §9.1). The trap this file exists to guard is
§9.3: net worth must be `quantity x average_cost`, not `sum(line.value)` —
the two formulas coincide for a euro-only ledger and diverge the moment a
holding is partly sold, which is exactly why the divergence needs its own
test rather than trusting the cash-envelope scenario to catch it.

Requires the `people_root` fixture (conftest.py).
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 024")
def test_net_worth() -> None:
    # TODO(024) — one test per site:
    #   - net worth includes person-account (People branch) balances
    #   - income and expense accounts are excluded (every entry balances, so
    #     including them would always report zero, design §9.2)
    #   - a negative person balance (you owe them) lowers net worth; a
    #     positive one (they owe you) raises it
    #
    # TODO(024) REGRESSION — buy 10 @ 100, sell 5 @ 130, starting from zero
    #   cash: net worth is 150 (the realised gain), not 0. This is the one
    #   test that fails the moment someone "simplifies" the total to
    #   sum(line.value) instead of quantity * average_cost (design §9.3).
    raise NotImplementedError
