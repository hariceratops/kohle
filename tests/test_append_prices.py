"""Layer 2 — use case against `session`.

`ListPriceTargets` and `AppendPrices` (issues 030, 031), design §6.3-§6.6, §7.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 030/031")
def test_list_price_targets_groups_by_plugin_and_symbol() -> None:
    # TODO(030/031) — one test per site:
    #   - two units on one binding
    #   - unbound units
    #   - non-security held unit absent from both
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 030/031")
def test_every_held_security_gets_exactly_one_outcome() -> None:
    # TODO(030/031) — one test per site:
    #   - priced (with previous shown), already stored, unpriced, unbound
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 030/031")
def test_second_run_writes_nothing() -> None:
    # TODO(030/031) — one test per site:
    #   - every unit reports already stored; no OperationGroup added
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 030/031")
def test_plugin_err_isolated_from_other_plugins() -> None:
    # TODO(030/031) — one test per site:
    #   - Err leaves its units unpriced with no rows
    #   - another plugin's rows still written
    #   - uninstalled plugin: Unpriced(UnknownPricePlugin)
    #   - missing result: MissingCloseResult
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 030/031")
def test_validation_rejections_are_per_unit() -> None:
    # TODO(030/031) — one test per site:
    #   - 031: zero, negative, future date, non-EUR each rejected with its own reason
    #   - another unit in the same run is still priced
    #   - an unrequested symbol lands in `ignored` and writes nothing
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 030/031")
def test_audit_trail_one_group_per_run() -> None:
    # TODO(030/031) — one test per site:
    #   - list-operations shows one `create prices` per new row in one group
    raise NotImplementedError
