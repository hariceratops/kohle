"""validate_statement, pure, no database (issues 026, 027)."""

import pytest


def test_validate_statement_rejects_malformed_rows() -> None:
    # TODO: empty/whitespace/None reference; duplicate across cash rows and across cash+security; unit_price None/0/-1/NaN; quantity 0; empty instrument_identifier; clean mixed list returns None; SecurityRow without unit_price raises TypeError.
    pytest.skip("scaffold")
