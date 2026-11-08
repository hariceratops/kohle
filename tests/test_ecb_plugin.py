"""Layer 2 — the ecb price plugin through its HTTP seam (issue 109). Design §7, §14."""

import pytest


@pytest.mark.skip(reason="TODO scaffold")
def test_returns_inr_as_a_price_in_eur() -> None:
    # TODO: the reciprocal of the quoted INR per EUR
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_unknown_code_is_unavailable() -> None:
    # TODO: Unavailable(no_symbol)
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_malformed_body_is_an_err() -> None:
    # TODO: never a guess
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_two_cubes() -> None:
    # TODO: recorded response with two dated cubes
    raise NotImplementedError
