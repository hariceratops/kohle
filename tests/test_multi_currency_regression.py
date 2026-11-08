"""Layer 3 — no regression without a currency unit (issues 107, 124). Design §14."""

import pytest


@pytest.mark.skip(reason="TODO scaffold")
def test_every_command_matches_the_107_baseline() -> None:
    # TODO: compare against the oracle captured in tests/fixtures by 107's first commit
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_eur_only_tables_are_byte_identical() -> None:
    # TODO: no quoted-in column, no subtotals, .2f prices
    raise NotImplementedError
