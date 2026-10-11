"""Layer 2 — use case against `session`.

`SetPriceSource` and the `price_bindings` table (issue 029), design §4.2, §5.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 029")
def test_refuses_unknown_unit_non_security_and_unknown_plugin() -> None:
    # TODO(029) — one test per site:
    #   - UnitNotFoundError
    #   - NotASecurityUnit for a non-security unit
    #   - unknown plugin name, with the available plugins named
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 029")
def test_rebinding_replaces_the_binding() -> None:
    # TODO(029) — one test per site:
    #   - binding twice leaves exactly one row, the second
    #   - an identical rebind adds no OperationGroup
    raise NotImplementedError
