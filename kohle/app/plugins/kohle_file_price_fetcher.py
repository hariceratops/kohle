import csv
import os
from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation

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

HEADER = ["identifier", "date", "close"]
HEADER_WITH_CURRENCY = [*HEADER, "currency"]
PRICE_FILE_VARIABLE = "KOHLE_PRICE_FILE"


class PriceFileUnreadable(PriceFetchError):
    def __init__(self, path: str, reason: str) -> None:
        super().__init__()
        self.path = path
        self.reason = reason

    def __str__(self) -> str:
        return f"Cannot read price file {self.path}: {self.reason}"


class MalformedPriceFile(PriceFetchError):
    def __init__(self, line: int, column: str, value: str, problem: str) -> None:
        super().__init__()
        self.line = line
        self.column = column
        self.value = value
        self.problem = problem

    def __str__(self) -> str:
        return f"Line {self.line}: column {self.column} {self.value!r} {self.problem}"


Rows = dict[str, dict[date, tuple[Decimal, str]]]


def _parse(reader) -> Result[Rows, PriceFetchError]:
    header: list[str] = next(reader, [])
    if header not in (HEADER, HEADER_WITH_CURRENCY):
        return Result.err(
            MalformedPriceFile(
                reader.line_num,
                "header",
                ",".join(header),
                f"is not {','.join(HEADER)!r} or {','.join(HEADER_WITH_CURRENCY)!r}",
            )
        )

    rows: Rows = {}
    for cells in reader:
        if not cells:
            continue
        line = reader.line_num
        if len(cells) != len(header):
            return Result.err(
                MalformedPriceFile(line, "row", ",".join(cells), f"has {len(cells)} fields, expected {len(header)}")
            )
        identifier, day_text, close_text, *rest = (cell.strip() for cell in cells)
        # A literal, not the ledger's base currency: the file's own default.
        currency = (rest[0] if rest else "") or "EUR"
        if not identifier:
            return Result.err(MalformedPriceFile(line, "identifier", identifier, "is required"))
        try:
            day = date.fromisoformat(day_text)
        except ValueError:
            return Result.err(MalformedPriceFile(line, "date", day_text, "is not an ISO date (YYYY-MM-DD)"))
        try:
            close = Decimal(close_text)
        except InvalidOperation:
            return Result.err(MalformedPriceFile(line, "close", close_text, "is not a decimal number"))
        days = rows.setdefault(identifier, {})
        if day in days:
            return Result.err(
                MalformedPriceFile(line, "row", f"{identifier},{day_text}", "repeats an earlier identifier and date")
            )
        days[day] = (close, currency)
    return Result.ok(rows)


class FilePriceFetcher(PriceFetcherPlugin):
    """Symbols looked up in the UTF-8 CSV named by `KOHLE_PRICE_FILE`, header `identifier,date,close`.

    Works offline. Each symbol gets its most recent row. The header may add a
    fourth column, `currency`; a row without one is claimed to be in EUR.
    """

    @property
    def name(self) -> str:
        return "file"

    def fetch_latest_closes(
        self, symbols: Sequence[str]
    ) -> Result[dict[str, PriceResult], PriceFetchError]:
        path = os.environ.get(PRICE_FILE_VARIABLE)
        if not path:
            return Result.err(MissingEnvironmentVariable(PRICE_FILE_VARIABLE))

        try:
            with open(path, encoding="utf-8", newline="") as price_file:
                parsed = _parse(csv.reader(price_file))
        except (OSError, UnicodeDecodeError, csv.Error) as e:
            return Result.err(PriceFileUnreadable(path, str(e)))
        if parsed.is_err:
            return Result.err(parsed.unwrap_err())
        rows = parsed.unwrap()

        results: dict[str, PriceResult] = {}
        for symbol in symbols:
            days = rows.get(symbol)
            if not days:
                results[symbol] = Unavailable(reason=UnavailableReason.no_symbol, detail=f"not in {path}")
                continue
            latest = max(days)
            close, currency = days[latest]
            results[symbol] = Close(price_date=latest, price=close, currency=currency)
        return Result.ok(results)
