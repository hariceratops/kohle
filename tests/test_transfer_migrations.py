"""Migrations for the transfer and remittance columns (issues 126, 132, 135). Design §18.8."""

import pytest


@pytest.mark.skip(reason="scaffold")
def test_each_migration_round_trips_and_refuses_an_offending_row() -> None:
    # TODO: §18.8: for migrations a, b, c a round trip when empty, a refusal with one offending row leaving the schema untouched, CHECKs reject a mirror without mirror_of_entry_id and a remittance without a unit, HEAD_REVISION pinned
    ...
