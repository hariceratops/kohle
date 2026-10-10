"""Layer 3 scenario for importer-plugins-for-assets (issue 028)."""

import pytest


def test_broker_statement_scenario() -> None:
    # TODO: design section 7.3 fixture end to end: three rows imported; Depot holds 6 units at average cost 95.50; the dividend is a debit on Broker Cash against Unclassified Income; a rule added before a fresh import reroutes it; re-import gives 0.
    pytest.skip("scaffold")
