"""Layer 2 — quote currency on bindings and closes (issues 107, 108). Design §5, §14."""

import pytest


@pytest.mark.skip(reason="TODO scaffold")
def test_inr_close_for_a_eur_binding_is_rejected() -> None:
    # TODO: prices unchanged
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_eur_close_for_an_inr_binding_is_rejected() -> None:
    # TODO: prices unchanged
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_set_price_source_binds_inr_in_eur_and_refuses_other_quotes() -> None:
    # TODO: EUR and commodities still NotASecurityUnit
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_rebinding_keeps_each_rows_own_currency() -> None:
    # TODO: no refusal while closes are stored
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_list_price_targets_includes_a_currency_only_held_via_shares() -> None:
    # TODO: INR when only INR-quoted shares are held
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_file_plugin_currency_column() -> None:
    # TODO: a 4-column header, and an empty currency cell defaulting to EUR
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_alphavantage_stamps_the_bindings_currency() -> None:
    # TODO: its one-argument call still says EUR
    raise NotImplementedError
