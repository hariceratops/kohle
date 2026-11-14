"""Layer 2 — the ecb price plugin through its HTTP seam (issue 109). Design §7, §14.

The bodies are recordings of the shape of `eurofxref-daily.xml`; no network.
"""

from datetime import date
from decimal import Decimal
from urllib.error import URLError

import pytest

from kohle.app.plugins.kohle_ecb_price_fetcher import (
    ENDPOINT,
    EcbPriceFetcher,
    EcbUnreachable,
    UnexpectedEcbResponse,
)
from kohle.plugin.price_plugin import Close, Unavailable, UnavailableReason

DAILY = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
<gesmes:subject>Reference rates</gesmes:subject>
<gesmes:Sender><gesmes:name>European Central Bank</gesmes:name></gesmes:Sender>
<Cube>
<Cube time='2026-11-06'>
<Cube currency='USD' rate='1.1500'/>
<Cube currency='JPY' rate='176.77'/>
<Cube currency='INR' rate='104.8645'/>
<Cube currency='IDR' rate='20208.93'/>
</Cube>
</Cube>
</gesmes:Envelope>"""

TWO_CUBES = DAILY.replace(
    b"</Cube>\n</Cube>", b"</Cube>\n<Cube time='2026-11-05'><Cube currency='INR' rate='105.0000'/></Cube>\n</Cube>"
)


def _fetcher(body: bytes, urls: list[str] | None = None) -> EcbPriceFetcher:
    def http_get(url: str) -> bytes:
        if urls is not None:
            urls.append(url)
        return body

    return EcbPriceFetcher(http_get=http_get)


def test_returns_inr_as_a_price_in_eur() -> None:
    urls: list[str] = []
    result = _fetcher(DAILY, urls).fetch_latest_closes(["INR", "IDR"])

    assert result.unwrap() == {
        "INR": Close(price_date=date(2026, 11, 6), price=Decimal("0.00953612"), currency="EUR"),
        "IDR": Close(price_date=date(2026, 11, 6), price=Decimal("0.00004948"), currency="EUR"),
    }
    assert urls == [ENDPOINT]


def test_unknown_code_is_unavailable() -> None:
    results = _fetcher(DAILY).fetch_latest_closes(["INR", "XYZ"]).unwrap()

    unavailable = results["XYZ"]
    assert isinstance(unavailable, Unavailable)
    assert unavailable.reason is UnavailableReason.no_symbol
    assert isinstance(results["INR"], Close)


@pytest.mark.parametrize(
    "body",
    [
        b"not xml at all",
        b"<Envelope xmlns='http://www.ecb.int/vocabulary/2002-08-01/eurofxref'><Cube/></Envelope>",
        DAILY.replace(b"104.8645", b"abc"),
        DAILY.replace(b"104.8645", b"0"),
        DAILY.replace(b"104.8645", b"-3"),
        DAILY.replace(b"2026-11-06", b"yesterday"),
    ],
)
def test_malformed_body_is_an_err(body: bytes) -> None:
    error = _fetcher(body).fetch_latest_closes(["INR"]).unwrap_err()

    assert isinstance(error, UnexpectedEcbResponse)


def test_two_cubes() -> None:
    error = _fetcher(TWO_CUBES).fetch_latest_closes(["INR"]).unwrap_err()

    assert isinstance(error, UnexpectedEcbResponse)


def test_unreachable_is_an_err() -> None:
    def http_get(url: str) -> bytes:
        raise URLError("offline")

    error = EcbPriceFetcher(http_get=http_get).fetch_latest_closes(["INR"]).unwrap_err()

    assert isinstance(error, EcbUnreachable)
