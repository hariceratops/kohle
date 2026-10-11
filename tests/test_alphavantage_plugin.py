"""Layer 1 — pure unit tests, fake `http_get` and recording `sleep`.

`AlphaVantagePriceFetcher` (issue 033), design §10. No live network.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 033")
def test_missing_key_is_a_plugin_error() -> None:
    # TODO(033) — one test per site:
    #   - Err, and http_get is never called
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 033")
def test_daily_response_gives_a_euro_close() -> None:
    # TODO(033) — one test per site:
    #   - daily.json fixture; assert the request URL
    #   - latest bar dated strictly before the current UTC date (in-progress day never chosen)
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 033")
def test_unknown_symbol_is_not_covered() -> None:
    # TODO(033) — one test per site:
    #   - unknown_symbol.json fixture (HTTP 200 with an Error Message body)
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 033")
def test_throttle_keeps_fetched_closes() -> None:
    # TODO(033) — one test per site:
    #   - throttled at the second of three symbols: first is a Close, other two transient, exactly two requests
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 033")
def test_burst_pause_between_requests_only() -> None:
    # TODO(033) — one test per site:
    #   - sleep(1) called between requests, not before the first
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 033")
def test_unreachable_and_unexpected_body_are_plugin_errors() -> None:
    # TODO(033) — one test per site:
    #   - URLError gives Err(AlphaVantageUnreachable)
    #   - HTML body gives Err(UnexpectedAlphaVantageResponse)
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 033")
def test_api_key_never_appears_in_output() -> None:
    # TODO(033) — one test per site:
    #   - TESTKEY in no detail and no error string (quota notice echoes the key)
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 033")
def test_oldest_close_first_ordering() -> None:
    # TODO(033) — one test per site:
    #   - pure ordering function: oldest stored close first, no stored close first, ties by symbol
    #   - two units on one symbol use the older close
    raise NotImplementedError
