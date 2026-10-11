"""Layer 3 — CLI through `CliRunner`.

`set-price-source` and `fetch-prices` (issues 029-033), design §5, §6.7, §15. `kohle.app.cli.cli.load_price_plugins` monkeypatched, as in the importer CLI tests.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 029-033")
def test_set_price_source_success_and_refusals() -> None:
    # TODO(029-033) — one test per site:
    #   - success
    #   - each refusal exits non-zero with its message
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 029-033")
def test_fetch_prices_with_the_file_plugin() -> None:
    # TODO(029-033) — one test per site:
    #   - real FilePriceFetcher, KOHLE_PRICE_FILE at a temp file: priced, then a re-run reports already stored for every unit
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 029-033")
def test_unbound_only_exits_zero() -> None:
    # TODO(029-033) — one test per site:
    #   - an unbound held unit is the only gap
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 029-033")
def test_unset_price_file_exits_one() -> None:
    # TODO(029-033) — one test per site:
    #   - message per unit
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 029-033")
def test_alphavantage_throttle_scenario() -> None:
    # TODO(029-033) — one test per site:
    #   - 033: exits 1 with one row stored (design §10.6)
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 029-033")
def test_nothing_held_says_so() -> None:
    # TODO(029-033) — one test per site:
    #   - prints `No held securities`
    raise NotImplementedError
