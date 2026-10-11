"""Layer 2 — use case against `session`, pinned `TODAY`.

`value_balances`, `ValuedNetWorth`, `QueryValuedBalance` in kohle/use_cases/reporting.py (issues 035, 036, 038). Design §4, §11. Closes are seeded with `session.add(Price(...))`, as test_latest_close does.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 035")
def test_value_balances_looks_up_only_nonzero_non_base_rows() -> None:
    # TODO(035) — one test per site:
    #   - REGRESSION: a zero-quantity security row gets close None even when its unit has a stored close (pins 'no close is looked up')
    #   - a euro row gets close None
    #   - an unbound security and a commodity come back NoClose
    #   - row order is preserved
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 035")
def test_staleness_boundary_at_the_use_case_level() -> None:
    # TODO(035) — one test per site:
    #   - N = 7: TODAY - 7 is Fresh, TODAY - 8 is Stale
    #   - N = 3: TODAY - 3 is Fresh, TODAY - 4 is Stale
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 035")
def test_valued_net_worth_on_a_mixed_ledger() -> None:
    # TODO(035) — one test per site:
    #   - euro cash, a fresh, a stale and a never-fetched security, a sold-out position, a euro receivable
    #   - a security held in two depots is one row: summed quantity x close
    #   - at-cost properties equal NetWorth(session).execute() on the same ledger
    #   - net_worth_at_market equals the sum of market_value over both sections
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 036")
def test_net_worth_estimates() -> None:
    # TODO(036) — one test per site:
    #   - estimates gives K, M, S and C on the mixed ledger
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 038")
def test_query_valued_balance() -> None:
    # TODO(038) — one test per site:
    #   - the same rule on a subtree
    #   - an unknown account is Err(AccountNotFoundError)
    raise NotImplementedError
