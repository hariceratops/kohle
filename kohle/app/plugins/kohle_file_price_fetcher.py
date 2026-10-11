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


Rows = dict[str, dict[date, Decimal]]


def _parse(reader) -> Result[Rows, PriceFetchError]:
    header: list[str] = next(reader, [])
    if header != HEADER:
        return Result.err(
            MalformedPriceFile(reader.line_num, "header", ",".join(header), f"is not {','.join(HEADER)!r}")
        )

    rows: Rows = {}
    for cells in reader:
        if not cells:
            continue
        line = reader.line_num
        if len(cells) != len(HEADER):
            return Result.err(
                MalformedPriceFile(line, "row", ",".join(cells), f"has {len(cells)} fields, expected {len(HEADER)}")
            )
        identifier, day_text, close_text = (cell.strip() for cell in cells)
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
        days[day] = close
    return Result.ok(rows)


class FilePriceFetcher(PriceFetcherPlugin):
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
            # A literal, not the ledger's base currency: this is the plugin's claim about its data.
            results[symbol] = Close(price_date=latest, price=days[latest], currency="EUR")
        return Result.ok(results)
