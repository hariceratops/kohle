"""Layer 1 — pure unit tests with temp files.

`FilePriceFetcher` (issue 030), design §9.
"""

import pytest


@pytest.mark.skip(reason="scaffold: issue 030")
def test_unset_empty_missing_or_undecodable_file_is_a_plugin_error() -> None:
    # TODO(030) — one test per site:
    #   - KOHLE_PRICE_FILE unset or empty (monkeypatch.setenv)
    #   - missing file
    #   - undecodable file
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 030")
def test_malformed_rows_are_plugin_errors() -> None:
    # TODO(030) — one test per site:
    #   - wrong header, short row, bad date, non-decimal close
    #   - repeated (identifier, date), with its line number
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 030")
def test_latest_row_per_symbol_and_absent_symbol() -> None:
    # TODO(030) — one test per site:
    #   - two dates for one symbol: the later one wins
    #   - absent symbol is Unavailable(no_symbol)
    #   - a zero close passes through as a Close (core validates it)
    raise NotImplementedError
