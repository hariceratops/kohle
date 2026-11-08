import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.request import urlopen

from kohle.core.result import Result
from kohle.plugin.price_plugin import (
    Close,
    PriceFetcherPlugin,
    PriceFetchError,
    PriceResult,
    Unavailable,
    UnavailableReason,
)

ENDPOINT = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
CUBE = "{http://www.ecb.int/vocabulary/2002-08-01/eurofxref}Cube"
PRICE_QUANTUM = Decimal("1E-8")


class EcbUnreachable(PriceFetchError):
    def __init__(self, reason: str) -> None:
        super().__init__()
        self.reason = reason

    def __str__(self) -> str:
        return f"Cannot reach the ECB: {self.reason}"


class UnexpectedEcbResponse(PriceFetchError):
    def __init__(self, problem: str) -> None:
        super().__init__()
        self.problem = problem

    def __str__(self) -> str:
        return f"Unexpected ECB response: {self.problem}"


def _urlopen_get(url: str) -> bytes:
    with urlopen(url, timeout=30) as response:
        return response.read()


def _parse_daily(body: bytes) -> tuple[date, dict[str, Decimal]]:
    """The one dated cube of the daily file and its rates, quoted per 1 EUR."""
    root = ET.fromstring(body)
    dated = [cube for cube in root.iter(CUBE) if "time" in cube.attrib]
    if len(dated) != 1:
        raise ValueError(f"expected exactly one dated cube, found {len(dated)}")
    day = date.fromisoformat(dated[0].attrib["time"])
    rates: dict[str, Decimal] = {}
    for cube in dated[0].iter(CUBE):
        if "currency" not in cube.attrib:
            continue
        rate = Decimal(cube.attrib["rate"])
        if not rate.is_finite() or rate <= 0:
            raise ValueError(f"rate for {cube.attrib['currency']} is not above zero")
        rates[cube.attrib["currency"]] = rate
    return day, rates


class EcbPriceFetcher(PriceFetcherPlugin):
    """ECB euro foreign exchange reference rates, by ISO currency code (for example `INR`).

    Needs network access, no key. Returns the price of one unit of the currency
    in euros: the reciprocal of the ECB's quote per euro, to 8 places. The rate
    is the latest working day's, fixed around 14:10 CET and published around
    16:00 CET. Source: ECB statistics.
    """

    def __init__(self, http_get: Callable[[str], bytes] = _urlopen_get) -> None:
        self._http_get = http_get

    @property
    def name(self) -> str:
        return "ecb"

    def fetch_latest_closes(
        self, symbols: Sequence[str]
    ) -> Result[dict[str, PriceResult], PriceFetchError]:
        try:
            body = self._http_get(ENDPOINT)
        except OSError as e:
            return Result.err(EcbUnreachable(str(e)))
        try:
            day, rates = _parse_daily(body)
        except (ET.ParseError, ValueError, KeyError, InvalidOperation) as e:
            return Result.err(UnexpectedEcbResponse(str(e)))

        results: dict[str, PriceResult] = {}
        for symbol in symbols:
            if symbol in rates:
                # The literal EUR: the reciprocal of a per-euro quote is a price in euros whatever the binding says.
                results[symbol] = Close(
                    price_date=day, price=(1 / rates[symbol]).quantize(PRICE_QUANTUM), currency="EUR"
                )
            else:
                results[symbol] = Unavailable(
                    reason=UnavailableReason.no_symbol,
                    detail=f"the ECB publishes no reference rate for {symbol}",
                )
        return Result.ok(results)
