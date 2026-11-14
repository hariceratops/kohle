"""Layer 2 — the nse price plugin through its HTTP seam (issue 110). Design §7, §14.

The archives are built here in the shape of the recorded 2026-11-06 UDiFF bhavcopy
(real header names, a few rows); no network.
"""

import io
import zipfile
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from urllib.error import HTTPError, URLError

from kohle.app.plugins.kohle_nse_price_fetcher import (
    HEADERS,
    NoBhavcopyFound,
    NsePriceFetcher,
    NseUnreachable,
    UnexpectedBhavcopy,
)
from kohle.plugin.price_plugin import Close, Unavailable, UnavailableReason

HEADER = "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,ClsPric,LastPric,PrvsClsgPric"
INFY = "INE009A01021"
BE_ONLY = "INE000BE0001"
FRIDAY = date(2026, 11, 6)
SATURDAY = date(2026, 11, 7)


def _zip(
    csv_text: str, name: str = "BhavCopy_NSE_CM_0_0_0_20261106_F_0000.csv"
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(name, csv_text)
    return buffer.getvalue()


def _bhavcopy(*rows: str, header: str = HEADER) -> bytes:
    return _zip("\n".join([header, *rows]) + "\n")


BHAVCOPY = _bhavcopy(
    f"2026-11-06,2026-11-06,CM,NSE,STK,1594,{INFY},INFY,EQ,1181.40,1180.00,1170.25",
    f"2026-11-06,2026-11-06,CM,NSE,STK,9001,{BE_ONLY},BEONLY,BE,55.10,55.00,54.00",
    "2026-11-06,2026-11-06,CM,NSE,STK,9002,INE000SM0002,SMCO,SM,12.00,12.00,11.00",
)


class _Server:
    """Serves archives by date; any other date is a 404."""

    def __init__(self, archives: dict[date, bytes]) -> None:
        self.archives = archives
        self.urls: list[str] = []
        self.headers: list[dict[str, str]] = []

    def get(self, url: str, headers: Mapping[str, str]) -> bytes:
        self.urls.append(url)
        self.headers.append(dict(headers))
        stamp = url.rsplit("_", 3)[-3]
        day = date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:]))
        if day not in self.archives:
            raise HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]
        return self.archives[day]


def _fetcher(server: _Server, today: date = FRIDAY) -> NsePriceFetcher:
    return NsePriceFetcher(http_get=server.get, today=lambda: today)


def test_close_for_an_isin_in_the_eq_series() -> None:
    server = _Server({FRIDAY: BHAVCOPY})

    result = _fetcher(server).fetch_latest_closes([INFY])

    assert result.unwrap() == {
        INFY: Close(price_date=FRIDAY, price=Decimal("1181.40"), currency="INR")
    }
    assert server.urls == [
        "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20261106_F_0000.csv.zip"
    ]
    assert server.headers[0] == HEADERS
    assert server.headers[0]["Referer"] == "https://www.nseindia.com/"
    assert "Mozilla" in server.headers[0]["User-Agent"]


def test_weekend_and_holiday_walk_back() -> None:
    # Sunday 2026-11-08 starts at Friday; Friday is a holiday, so Thursday is read.
    thursday = date(2026, 11, 5)
    thursday_copy = _bhavcopy(
        f"2026-11-05,2026-11-05,CM,NSE,STK,1594,{INFY},INFY,EQ,1170.25,1180.00,1160.00"
    )
    server = _Server({thursday: thursday_copy})

    result = _fetcher(server, today=date(2026, 11, 8)).fetch_latest_closes([INFY])

    assert result.unwrap() == {
        INFY: Close(price_date=thursday, price=Decimal("1170.25"), currency="INR")
    }
    assert [u.rsplit("_", 3)[-3] for u in server.urls] == ["20261106", "20261105"]


def test_ten_weekday_limit() -> None:
    server = _Server({})

    error = _fetcher(server, today=SATURDAY).fetch_latest_closes([INFY]).unwrap_err()

    assert isinstance(error, NoBhavcopyFound)
    assert len(server.urls) == 10
    assert (error.first, error.last) == (FRIDAY, date(2026, 10, 26))


def test_missing_column_is_an_err() -> None:
    header = HEADER.replace(",ClsPric", "")
    server = _Server(
        {
            FRIDAY: _bhavcopy(
                f"2026-11-06,2026-11-06,CM,NSE,STK,1594,{INFY},INFY,EQ,1180.00,1170.25",
                header=header,
            )
        }
    )

    error = _fetcher(server).fetch_latest_closes([INFY]).unwrap_err()

    assert isinstance(error, UnexpectedBhavcopy)
    assert "ClsPric" in str(error)


def test_isin_with_only_a_be_row_is_unavailable() -> None:
    result = _fetcher(_Server({FRIDAY: BHAVCOPY})).fetch_latest_closes(
        [BE_ONLY, "INE000XX0000"]
    )

    for symbol in (BE_ONLY, "INE000XX0000"):
        outcome = result.unwrap()[symbol]
        assert isinstance(outcome, Unavailable)
        assert outcome.reason is UnavailableReason.no_symbol
        assert symbol in outcome.detail
        assert "2026-11-06" in outcome.detail


def test_duplicate_eq_row() -> None:
    row = (
        f"2026-11-06,2026-11-06,CM,NSE,STK,1594,{INFY},INFY,EQ,1181.40,1180.00,1170.25"
    )
    server = _Server({FRIDAY: _bhavcopy(row, row)})

    error = _fetcher(server).fetch_latest_closes([INFY]).unwrap_err()

    assert isinstance(error, UnexpectedBhavcopy)


def test_row_dated_other_than_the_file_is_an_err() -> None:
    server = _Server(
        {
            FRIDAY: _bhavcopy(
                f"2026-11-05,2026-11-05,CM,NSE,STK,1594,{INFY},INFY,EQ,1181.40,1180.00,1170.25"
            )
        }
    )

    assert isinstance(
        _fetcher(server).fetch_latest_closes([INFY]).unwrap_err(), UnexpectedBhavcopy
    )


def test_unreachable_host() -> None:
    def refuse(url: str, headers: Mapping[str, str]) -> bytes:
        raise URLError("Name or service not known")

    error = (
        NsePriceFetcher(http_get=refuse, today=lambda: FRIDAY)
        .fetch_latest_closes([INFY])
        .unwrap_err()
    )

    assert isinstance(error, NseUnreachable)
    assert "Name or service not known" in str(error)


def test_http_error_other_than_404_is_unreachable() -> None:
    def forbidden(url: str, headers: Mapping[str, str]) -> bytes:
        raise HTTPError(url, 403, "Forbidden", {}, None)  # type: ignore[arg-type]

    error = (
        NsePriceFetcher(http_get=forbidden, today=lambda: FRIDAY)
        .fetch_latest_closes([INFY])
        .unwrap_err()
    )

    assert isinstance(error, NseUnreachable)
