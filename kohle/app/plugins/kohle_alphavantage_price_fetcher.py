import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from kohle.core.result import Result
from kohle.plugin.price_plugin import (
    Close,
    MissingEnvironmentVariable,
    PriceFetcherPlugin,
    PriceFetchError,
    PriceResult,
    Unavailable,
    UnavailableReason,
)

KEY_VARIABLE = "KOHLE_ALPHAVANTAGE_KEY"
ENDPOINT = "https://www.alphavantage.co/query"
SERIES_KEY = "Time Series (Daily)"
CLOSE_KEY = "4. close"
BURST_PAUSE_SECONDS = 1


class AlphaVantageUnreachable(PriceFetchError):
    def __init__(self, reason: str) -> None:
        super().__init__()
        self.reason = reason

    def __str__(self) -> str:
        return f"Cannot reach Alpha Vantage: {self.reason}"


class UnexpectedAlphaVantageResponse(PriceFetchError):
    def __init__(self, symbol: str, problem: str) -> None:
        super().__init__()
        self.symbol = symbol
        self.problem = problem

    def __str__(self) -> str:
        return f"Unexpected Alpha Vantage response for {self.symbol}: {self.problem}"


def _urlopen_get(url: str) -> bytes:
    with urlopen(url, timeout=30) as response:
        return response.read()


def _latest_finished_close(series: Mapping[str, Mapping[str, str]], before: date) -> tuple[date, Decimal] | None:
    """The newest bar dated strictly before `before`, so a day still in progress is never chosen."""
    finished = [day for day in (date.fromisoformat(text) for text in series) if day < before]
    if not finished:
        return None
    latest = max(finished)
    return latest, Decimal(series[latest.isoformat()][CLOSE_KEY])


class AlphaVantagePriceFetcher(PriceFetcherPlugin):
    def __init__(
        self,
        http_get: Callable[[str], bytes] = _urlopen_get,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http_get = http_get
        self._sleep = sleep

    @property
    def name(self) -> str:
        return "alphavantage"

    def fetch_latest_closes(
        self, symbols: Sequence[str]
    ) -> Result[dict[str, PriceResult], PriceFetchError]:
        key = os.environ.get(KEY_VARIABLE)
        if not key:
            return Result.err(MissingEnvironmentVariable(KEY_VARIABLE))

        def redact(text: str) -> str:
            return text.replace(key, "***")

        results: dict[str, PriceResult] = {}
        throttled: Unavailable | None = None
        requested = 0
        for symbol in symbols:
            # Not sorted or deduplicated: core orders symbols so a quota is spent on the stalest first.
            if throttled is not None:
                results[symbol] = throttled
                continue
            if requested:
                self._sleep(BURST_PAUSE_SECONDS)
            requested += 1

            url = f"{ENDPOINT}?{urlencode({'function': 'TIME_SERIES_DAILY', 'symbol': symbol, 'apikey': key})}"
            try:
                body = self._http_get(url)
            except OSError as e:
                return Result.err(AlphaVantageUnreachable(redact(str(e))))
            try:
                payload: Any = json.loads(body)
            except ValueError as e:
                return Result.err(UnexpectedAlphaVantageResponse(symbol, redact(f"body is not JSON: {e}")))
            if not isinstance(payload, dict):
                return Result.err(UnexpectedAlphaVantageResponse(symbol, "body is not a JSON object"))

            # By which key is present, never by message wording: the burst and daily notices overlap in text.
            if SERIES_KEY in payload:
                try:
                    found = _latest_finished_close(payload[SERIES_KEY], datetime.now(UTC).date())
                except (ValueError, ArithmeticError, KeyError, TypeError, AttributeError) as e:
                    return Result.err(
                        UnexpectedAlphaVantageResponse(symbol, redact(f"unreadable daily series: {e!r}"))
                    )
                if found is None:
                    results[symbol] = Unavailable(
                        reason=UnavailableReason.transient, detail="no finished daily close yet"
                    )
                else:
                    day, price = found
                    # A literal, not the ledger's base currency: this is the plugin's claim about its data.
                    results[symbol] = Close(price_date=day, price=price, currency="EUR")
            elif "Error Message" in payload:
                results[symbol] = Unavailable(
                    reason=UnavailableReason.not_covered, detail=redact(str(payload["Error Message"]))
                )
            elif "Information" in payload:
                throttled = Unavailable(
                    reason=UnavailableReason.transient, detail=redact(str(payload["Information"]))
                )
                results[symbol] = throttled
            else:
                return Result.err(
                    UnexpectedAlphaVantageResponse(symbol, "no daily series, error message or information notice")
                )
        return Result.ok(results)
