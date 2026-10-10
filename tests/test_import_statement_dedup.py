"""ImportStatement dedup and atomicity (issue 026)."""

import pytest


def test_reimport_writes_nothing() -> None:
    # TODO: second import returns 0 and OperationGroup count is unchanged; reference == f'{cash.id}:{native}'; same rows into two cash accounts give two entries each; same reference with enriched counterparty imports 0 (replaces test_counterparty_is_not_part_of_the_reference_hash); malformed last row leaves every table unchanged; missing/duplicate reference rejects; failing plugin writes nothing.
    pytest.skip("scaffold")
