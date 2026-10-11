"""Layer 3 — CLI through `CliRunner` with `session_factory`.

`net-worth` and `balance` market value, estimates and `--max-age-days` (issues 035-038). Design §6, §11.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 035")
def test_net_worth_columns_and_lines() -> None:
    # TODO(035) — one test per site:
    #   - header tokens exactly: section unit quantity price price date market value status at cost
    #   - each data row's last token is its formatted at-cost value
    #   - 'Net worth (at cost): X' matches verbatim
    #   - status cells contain spaces: assert them by substring within a row
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 036")
def test_net_worth_always_prints_market_and_summary() -> None:
    # TODO(036) — one test per site:
    #   - euro-only ledger (M = 0): last two lines are 'Net worth (at market): X' and '0 of 0 holdings estimated'
    #   - mixed ledger: the summary carries K, M, S and C
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 037")
def test_net_worth_max_age_days() -> None:
    # TODO(037) — one test per site:
    #   - -1 and x exit 2 with an obj= factory that fails the test if called (forbidden_session_local pattern)
    #   - boundary pair via the monkeypatched kohle.app.cli.cli.date
    #   - a mid-range check seeded relative to real date.today() with ages well away from N
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 038")
def test_balance_columns_and_restatement_row() -> None:
    # TODO(038) — one test per site:
    #   - header order: unit quantity price price date market value status average cost
    #   - 'Total (base currency)' row: '-' in price, price date, status, average cost; quantity in market value
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 038")
def test_balance_market_lines_only_for_non_base_holdings() -> None:
    # TODO(038) — one test per site:
    #   - a euro-only account (M = 0) prints neither 'Market value' nor 'holdings estimated'
    #   - a mixed account prints both as the last two lines; X is the sum of unit rows only
    #   - a mixed account with K = 0 prints '0 of M holdings estimated'
    #   - REGRESSION: an account whose only non-euro row is sold out (M = 0) prints neither line: the gate is M, not 'any non-base row'
    #   - 'No holdings' output unchanged
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 038")
def test_balance_max_age_days() -> None:
    # TODO(038) — one test per site:
    #   - same flag, same behaviour as net-worth
    raise NotImplementedError
