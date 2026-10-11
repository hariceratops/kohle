"""Layer 1 — pure unit tests, no fixture.

The price-fetcher contract and `plugin_manager` kind partitioning (issue 029). dev/design/price-fetcher-plugin.md §2, §3.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 029")
def test_load_plugins_returns_only_importers() -> None:
    # TODO(029) — one test per site:
    #   - entry_points patched to a mix of both kinds; load_plugins() returns importers only
    #   - load_price_plugins() returns price plugins only
    #   - a name shared across kinds is fine
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 029")
def test_class_of_neither_kind_raises_type_error() -> None:
    # TODO(029) — one test per site:
    #   - a plugin class subclassing neither ABC raises TypeError
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 029")
def test_duplicate_name_within_a_kind_names_the_plugin() -> None:
    # TODO(029) — one test per site:
    #   - REGRESSION: the ValueError message interpolates the name (the misplaced f-prefix fix, spec Technical Approach)
    raise NotImplementedError
