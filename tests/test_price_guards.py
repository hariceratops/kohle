"""Layer 4 — structural guards.

Issue 034, design §11. The separation of recorded books from fetched prices is structural, so a test fails if someone wires them together.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 034")
def test_recording_and_import_code_never_reference_prices() -> None:
    # TODO(034) — one test per site:
    #   - AST walk: exact identifiers (Price, PriceBinding, PriceFetcherPlugin, load_price_plugins) and the price modules, not substrings (`unit_price` is recording vocabulary)
    #   - subprocess: price modules absent from sys.modules after importing the use-case modules
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 034")
def test_no_price_plugins_means_no_output_change() -> None:
    # TODO(034) — one test per site:
    #   - scripted existing commands run twice, once with price entry points filtered out; outputs identical
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 034")
def test_third_plugin_binds_and_fetches_without_core_changes() -> None:
    # TODO(034) — one test per site:
    #   - test-local PriceFetcherPlugin via a patched entry_points EntryPoint; set-price-source then fetch-prices stores the close
    raise NotImplementedError
