import csv
import io
import zipfile
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from kohle.core.result import Result
from kohle.plugin.price_plugin import (
    Close,
    PriceFetcherPlugin,
    PriceFetchError,
    PriceResult,
    Unavailable,
    UnavailableReason,
)

URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"
# NSE drops the connection of a request without browser-like headers.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "https://www.nseindia.com/",
    "Accept": "*/*",
}
MAX_WEEKDAYS = 10
REQUIRED_COLUMNS = ("TradDt", "ISIN", "SctySrs", "ClsPric")


class NseUnreachable(PriceFetchError):
    def __init__(self, reason: str) -> None:
        super().__init__()
        self.reason = reason

    def __str__(self) -> str:
        return f"Cannot reach NSE: {self.reason}"


class NoBhavcopyFound(PriceFetchError):
    def __init__(self, first: date, last: date) -> None:
        super().__init__()
        self.first = first
        self.last = last

    def __str__(self) -> str:
        return f"No NSE bhavcopy found for any weekday from {self.first} back to {self.last}"


class UnexpectedBhavcopy(PriceFetchError):
    def __init__(self, problem: str) -> None:
        super().__init__()
        self.problem = problem

    def __str__(self) -> str:
        return f"Unexpected NSE bhavcopy: {self.problem}"


def _urlopen_get(url: str, headers: Mapping[str, str]) -> bytes:
    with urlopen(Request(url, headers=dict(headers)), timeout=30) as response:
        return response.read()


def _latest_weekday(day: date) -> date:
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _previous_weekday(day: date) -> date:
    return _latest_weekday(day - timedelta(days=1))


def _read_rows(archive: bytes) -> list[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        members = [name for name in zf.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError(
                f"expected exactly one CSV in the zip, found {len(members)}"
            )
        reader = csv.DictReader(io.StringIO(zf.read(members[0]).decode("utf-8-sig")))
        missing = [
            column
            for column in REQUIRED_COLUMNS
            if column not in (reader.fieldnames or [])
        ]
        if missing:
            raise ValueError(f"missing column(s) {', '.join(missing)}")
        return list(reader)


class NsePriceFetcher(PriceFetcherPlugin):
    """NSE end-of-day close from the UDiFF bhavcopy, by ISIN (for example `INE009A01021`).

    Needs network access, no key. Reads the `EQ` series only, so a stock moved
    to another series such as `BE` is unavailable. Returns the official close in
    INR from the latest weekday's file, stepping back over holidays. The file is
    published after the close. The terms of use of the archive are unverified.
    """

    def __init__(
        self,
        http_get: Callable[[str, Mapping[str, str]], bytes] = _urlopen_get,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._http_get = http_get
        self._today = today

    @property
    def name(self) -> str:
        return "nse"

    def fetch_latest_closes(
        self, symbols: Sequence[str]
    ) -> Result[dict[str, PriceResult], PriceFetchError]:
        first = day = _latest_weekday(self._today())
        archive: bytes | None = None
        for attempt in range(MAX_WEEKDAYS):
            if attempt:
                day = _previous_weekday(day)
            try:
                archive = self._http_get(URL.format(day=day), HEADERS)
                break
            except HTTPError as e:
                if e.code != 404:
                    return Result.err(NseUnreachable(f"HTTP {e.code} for {day}"))
            except OSError as e:
                return Result.err(NseUnreachable(str(e)))
        if archive is None:
            return Result.err(NoBhavcopyFound(first, day))

        try:
            rows = _read_rows(archive)
        except (zipfile.BadZipFile, ValueError) as e:
            return Result.err(UnexpectedBhavcopy(str(e)))

        eq_rows: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            if row["SctySrs"] == "EQ":
                eq_rows.setdefault(row["ISIN"], []).append(row)

        results: dict[str, PriceResult] = {}
        for symbol in symbols:
            found = eq_rows.get(symbol, [])
            if not found:
                results[symbol] = Unavailable(
                    reason=UnavailableReason.no_symbol,
                    detail=f"no EQ row for {symbol} in the bhavcopy of {day} (only the EQ series is read)",
                )
                continue
            if len(found) > 1:
                return Result.err(
                    UnexpectedBhavcopy(f"{len(found)} EQ rows for {symbol}")
                )
            try:
                price_date = date.fromisoformat(found[0]["TradDt"])
                price = Decimal(found[0]["ClsPric"])
            except (ValueError, InvalidOperation) as e:
                return Result.err(
                    UnexpectedBhavcopy(f"unreadable row for {symbol}: {e}")
                )
            if price_date != day:
                return Result.err(
                    UnexpectedBhavcopy(
                        f"row for {symbol} is dated {price_date} in the file of {day}"
                    )
                )
            results[symbol] = Close(price_date=price_date, price=price, currency="INR")
        return Result.ok(results)
