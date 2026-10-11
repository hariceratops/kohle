"""Layer 1 — pure unit tests, fake `http_get` and recording `sleep`.

`AlphaVantagePriceFetcher` (issue 033), design §10, and `oldest_close_first`,
design §6.4. No live network.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

import pytest

from kohle.app.plugins.kohle_alphavantage_price_fetcher import (
    AlphaVantagePriceFetcher,
    AlphaVantageUnreachable,
    UnexpectedAlphaVantageResponse,
    _latest_finished_close,
)
from kohle.plugin.price_plugin import (
    Close,
    MissingEnvironmentVariable,
    Unavailable,
    UnavailableReason,
)
from kohle.use_cases.prices import oldest_close_first

FIXTURES = Path(__file__).parent / "fixtures" / "alphavantage"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class _Fake:
    """Answers each request from `bodies` by its `symbol` query parameter and records the URLs."""

    def __init__(self, bodies: dict[str, bytes | Exception]) -> None:
        self.bodies = bodies
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        body = self.bodies[self.symbols[-1]]
        if isinstance(body, Exception):
            raise body
        return body

    @property
    def symbols(self) -> list[str]:
        return [parse_qs(urlparse(url).query)["symbol"][0] for url in self.urls]


def _plugin(fake: Callable[[str], bytes], sleeps: list[float] | None = None) -> AlphaVantagePriceFetcher:
    return AlphaVantagePriceFetcher(http_get=fake, sleep=(sleeps if sleeps is not None else []).append)


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KOHLE_ALPHAVANTAGE_KEY", "TESTKEY")


def test_missing_key_is_a_plugin_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _Fake({})
    for value in (None, ""):
        if value is None:
            monkeypatch.delenv("KOHLE_ALPHAVANTAGE_KEY")
        else:
            monkeypatch.setenv("KOHLE_ALPHAVANTAGE_KEY", value)

        result = _plugin(fake).fetch_latest_closes(["IBM"])

        assert result.is_err
        error = result.unwrap_err()
        assert isinstance(error, MissingEnvironmentVariable)
        assert error.variable == "KOHLE_ALPHAVANTAGE_KEY"
    assert fake.urls == []


def test_name_and_construction_do_no_io(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KOHLE_ALPHAVANTAGE_KEY")

    assert AlphaVantagePriceFetcher().name == "alphavantage"


def test_daily_response_gives_a_euro_close() -> None:
    fake = _Fake({"IBM": _fixture("daily.json")})

    result = _plugin(fake).fetch_latest_closes(["IBM"]).unwrap()

    assert result == {"IBM": Close(price_date=date(2026, 10, 9), price=Decimal("227.1300"), currency="EUR")}
    (url,) = fake.urls
    query = parse_qs(urlparse(url).query)
    assert url.startswith("https://www.alphavantage.co/query?")
    assert query == {"function": ["TIME_SERIES_DAILY"], "symbol": ["IBM"], "apikey": ["TESTKEY"]}


def test_latest_finished_close_skips_the_day_in_progress() -> None:
    series = {
        "2026-10-09": {"4. close": "3"},
        "2026-10-08": {"4. close": "2"},
        "2026-10-07": {"4. close": "1"},
    }

    assert _latest_finished_close(series, before=date(2026, 10, 9)) == (date(2026, 10, 8), Decimal(2))
    assert _latest_finished_close(series, before=date(2026, 10, 10)) == (date(2026, 10, 9), Decimal(3))
    assert _latest_finished_close(series, before=date(2026, 10, 7)) is None
    assert _latest_finished_close({}, before=date(2026, 10, 9)) is None


def test_series_with_only_todays_bar_is_transient() -> None:
    today_bar = f'{{"Time Series (Daily)": {{"{datetime.now(UTC).date()}": {{"4. close": "1"}}}}}}'.encode()

    result = _plugin(_Fake({"NEW": today_bar})).fetch_latest_closes(["NEW"]).unwrap()

    assert result == {
        "NEW": Unavailable(reason=UnavailableReason.transient, detail="no finished daily close yet")
    }


def test_unknown_symbol_is_not_covered() -> None:
    result = _plugin(_Fake({"NOPE": _fixture("unknown_symbol.json")})).fetch_latest_closes(["NOPE"]).unwrap()

    unavailable = result["NOPE"]
    assert isinstance(unavailable, Unavailable)
    assert unavailable.reason is UnavailableReason.not_covered
    assert unavailable.detail.startswith("Invalid API call")


def test_throttle_keeps_fetched_closes() -> None:
    fake = _Fake({"A": _fixture("daily.json"), "B": _fixture("daily_limit.json"), "C": _fixture("daily.json")})

    result = _plugin(fake).fetch_latest_closes(["A", "B", "C"]).unwrap()

    assert isinstance(result["A"], Close)
    for symbol in ("B", "C"):
        unavailable = result[symbol]
        assert isinstance(unavailable, Unavailable)
        assert unavailable.reason is UnavailableReason.transient
        assert "rate limit" in unavailable.detail
    assert fake.symbols == ["A", "B"]


def test_demo_key_refusal_is_throttle_class() -> None:
    fake = _Fake({"A": _fixture("demo_key_refused.json"), "B": _fixture("daily.json")})

    result = _plugin(fake).fetch_latest_closes(["A", "B"]).unwrap()

    assert all(
        isinstance(r, Unavailable) and r.reason is UnavailableReason.transient for r in result.values()
    )
    assert fake.symbols == ["A"]


def test_requests_keep_the_order_given() -> None:
    symbols = ["ZZZ", "AAA", "MMM", "AAA2"]
    fake = _Fake({s: _fixture("daily.json") for s in symbols})

    result = _plugin(fake).fetch_latest_closes(symbols).unwrap()

    assert fake.symbols == symbols
    assert list(result) == symbols


def test_burst_pause_between_requests_only() -> None:
    sleeps: list[float] = []
    fake = _Fake({s: _fixture("daily.json") for s in "ABC"})

    _plugin(fake, sleeps).fetch_latest_closes(["A", "B", "C"]).unwrap()
    assert sleeps == [1, 1]

    sleeps.clear()
    _plugin(fake, sleeps).fetch_latest_closes(["A"]).unwrap()
    assert sleeps == []

    sleeps.clear()
    throttled = _Fake({"A": _fixture("daily.json"), "B": _fixture("daily_limit.json"), "C": b"{}"})
    _plugin(throttled, sleeps).fetch_latest_closes(["A", "B", "C"]).unwrap()
    assert sleeps == [1]


def test_unreachable_and_unexpected_body_are_plugin_errors() -> None:
    unreachable = _plugin(_Fake({"A": URLError("no route")})).fetch_latest_closes(["A"])
    assert isinstance(unreachable.unwrap_err(), AlphaVantageUnreachable)

    for body in (b"<html>Cloudflare</html>", b"[]", b"{}", b'{"Note": "old style"}'):
        result = _plugin(_Fake({"A": body})).fetch_latest_closes(["A"])
        assert isinstance(result.unwrap_err(), UnexpectedAlphaVantageResponse), body


def test_mid_run_transport_failure_is_a_plugin_error() -> None:
    fake = _Fake({"A": _fixture("daily.json"), "B": URLError("dropped")})

    assert isinstance(_plugin(fake).fetch_latest_closes(["A", "B"]).unwrap_err(), AlphaVantageUnreachable)


def test_unreadable_series_is_a_plugin_error() -> None:
    bad_close = b'{"Time Series (Daily)": {"2026-01-02": {"4. close": "abc"}}}'
    bad_date = b'{"Time Series (Daily)": {"nope": {"4. close": "1"}}}'
    missing_close = b'{"Time Series (Daily)": {"2026-01-02": {}}}'

    for body in (bad_close, bad_date, missing_close):
        result = _plugin(_Fake({"A": body})).fetch_latest_closes(["A"])
        assert isinstance(result.unwrap_err(), UnexpectedAlphaVantageResponse), body


def test_api_key_never_appears_in_output() -> None:
    # daily_limit.json is reconstructed from third-party reports, not recorded: it needs an exhausted real quota.
    throttled = _plugin(_Fake({"A": _fixture("daily_limit.json")})).fetch_latest_closes(["A"]).unwrap()
    detail = throttled["A"]
    assert isinstance(detail, Unavailable)
    assert "TESTKEY" not in detail.detail
    assert "***" in detail.detail
    assert "TESTKEY" not in str(detail)

    echoed = b'{"Error Message": "bad key TESTKEY"}'
    not_covered = _plugin(_Fake({"A": echoed})).fetch_latest_closes(["A"]).unwrap()["A"]
    assert isinstance(not_covered, Unavailable)
    assert "TESTKEY" not in not_covered.detail

    for fake in (_Fake({"A": URLError("failed for TESTKEY")}), _Fake({"A": b"TESTKEY is not json"})):
        error = _plugin(fake).fetch_latest_closes(["A"]).unwrap_err()
        assert "TESTKEY" not in str(error)


D1, D2, D3 = date(2026, 3, 1), date(2026, 3, 2), date(2026, 3, 3)


def test_oldest_close_first_ordering() -> None:
    stored: dict[str, Sequence[date | None]] = {
        "D": [D3],
        "C": [D1],
        "B": [D1],
        "A": [D2],
        "NEW": [None],
    }

    assert oldest_close_first(stored) == ["NEW", "B", "C", "A", "D"]
    assert oldest_close_first({}) == []


def test_oldest_close_first_ranks_a_shared_symbol_by_its_oldest_unit() -> None:
    assert oldest_close_first({"S": [D3, D1], "T": [D2]}) == ["S", "T"]
    assert oldest_close_first({"S": [D3, None], "T": [D1], "U": [None]}) == ["S", "U", "T"]


def test_rotation_refreshes_every_symbol_at_least_every_two_runs() -> None:
    symbols = [f"S{n:02d}" for n in range(30)]
    quota = 25
    latest: dict[str, date | None] = dict.fromkeys(symbols)
    refreshed_on: dict[str, list[int]] = {s: [] for s in symbols}

    for run in range(10):
        day = date(2026, 1, 1) + timedelta(days=run)
        for symbol in oldest_close_first({s: [d] for s, d in latest.items()})[:quota]:
            latest[symbol] = day
            refreshed_on[symbol].append(run)

    for symbol, runs in refreshed_on.items():
        assert runs, symbol
        assert all(b - a <= 2 for a, b in pairwise(runs)), (symbol, runs)
    assert max(runs[0] for runs in refreshed_on.values()) <= 1
