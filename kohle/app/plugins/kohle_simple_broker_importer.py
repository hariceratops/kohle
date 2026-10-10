import csv
from datetime import date
from decimal import Decimal, InvalidOperation

from kohle.core.result import Result
from kohle.plugin.importer_plugin import (
    CashRow,
    ImportError,
    SecurityRow,
    StatementImporterPlugin,
    StatementRow,
    StatementUnreadable,
)

HEADER = ["date", "reference", "type", "isin", "quantity", "price", "amount"]


class UnexpectedHeader(ImportError):
    def __init__(self, found: list[str]) -> None:
        super().__init__()
        self.found = found

    def __str__(self) -> str:
        return f"Unexpected header {','.join(self.found)!r}, expected {','.join(HEADER)!r}"


class UnknownRowType(ImportError):
    def __init__(self, line: int, value: str) -> None:
        super().__init__()
        self.line = line
        self.value = value

    def __str__(self) -> str:
        return f"Line {self.line}: unknown row type {self.value!r}, expected buy, sell or dividend"


class MalformedField(ImportError):
    def __init__(self, line: int, column: str, value: str, problem: str) -> None:
        super().__init__()
        self.line = line
        self.column = column
        self.value = value
        self.problem = problem

    def __str__(self) -> str:
        return f"Line {self.line}: column {self.column} {self.value!r} {self.problem}"


def _decimal(line: int, column: str, text: str) -> Result[Decimal, MalformedField]:
    try:
        value = Decimal(text)
    except InvalidOperation:
        return Result.err(MalformedField(line, column, text, "is not a decimal number"))
    if not value.is_finite():
        return Result.err(MalformedField(line, column, text, "is not a finite number"))
    return Result.ok(value)


def _positive(line: int, column: str, text: str) -> Result[Decimal, MalformedField]:
    parsed = _decimal(line, column, text)
    if parsed.is_ok and parsed.unwrap() <= 0:
        return Result.err(MalformedField(line, column, text, "must be greater than zero"))
    return parsed


def _must_be_empty(line: int, fields: dict[str, str], *columns: str) -> MalformedField | None:
    for column in columns:
        if fields[column]:
            return MalformedField(line, column, fields[column], "must be empty for this row type")
    return None


def _required(line: int, fields: dict[str, str], column: str) -> MalformedField | None:
    if not fields[column]:
        return MalformedField(line, column, "", "is required")
    return None


def _parse_row(line: int, fields: dict[str, str]) -> Result[StatementRow, ImportError]:
    row_type = fields["type"]
    if row_type not in ("buy", "sell", "dividend"):
        return Result.err(UnknownRowType(line, row_type))

    if missing := _required(line, fields, "date"):
        return Result.err(missing)
    try:
        entry_date = date.fromisoformat(fields["date"])
    except ValueError:
        return Result.err(MalformedField(line, "date", fields["date"], "is not an ISO date (YYYY-MM-DD)"))

    isin = fields["isin"]
    reference = fields["reference"]

    if row_type == "dividend":
        if problem := _must_be_empty(line, fields, "quantity", "price"):
            return Result.err(problem)
        if problem := _required(line, fields, "amount"):
            return Result.err(problem)
        amount = _decimal(line, "amount", fields["amount"])
        if amount.is_err:
            return Result.err(amount.unwrap_err())
        return Result.ok(
            CashRow(
                entry_date=entry_date,
                reference=reference,
                description=f"Dividend {isin}" if isin else "Dividend",
                amount=amount.unwrap(),
                counterparty_name=None,
                counterparty_iban=None,
            )
        )

    if problem := _must_be_empty(line, fields, "amount"):
        return Result.err(problem)
    for column in ("isin", "quantity", "price"):
        if problem := _required(line, fields, column):
            return Result.err(problem)
    quantity = _positive(line, "quantity", fields["quantity"])
    if quantity.is_err:
        return Result.err(quantity.unwrap_err())
    price = _positive(line, "price", fields["price"])
    if price.is_err:
        return Result.err(price.unwrap_err())

    sign = 1 if row_type == "buy" else -1
    return Result.ok(
        SecurityRow(
            entry_date=entry_date,
            reference=reference,
            description=f"{row_type.capitalize()} {isin}",
            instrument_identifier=isin,
            quantity=sign * quantity.unwrap(),
            unit_price=price.unwrap(),
        )
    )


class SimpleBrokerStatementImporter(StatementImporterPlugin):
    @property
    def name(self) -> str:
        return "kohle-simple-broker"

    def import_statement(self, statement_path: str) -> Result[list[StatementRow], ImportError]:
        try:
            with open(statement_path, encoding="utf-8", newline="") as statement:
                return self._parse(csv.reader(statement))
        except (OSError, UnicodeDecodeError, csv.Error) as e:
            return Result.err(StatementUnreadable(statement_path, str(e)))

    def _parse(self, reader) -> Result[list[StatementRow], ImportError]:
        header: list[str] = next(reader, [])
        if header != HEADER:
            return Result.err(UnexpectedHeader(header))

        rows: list[StatementRow] = []
        for cells in reader:
            if not cells:
                continue
            if len(cells) != len(HEADER):
                return Result.err(
                    MalformedField(reader.line_num, "row", ",".join(cells), f"has {len(cells)} fields, expected {len(HEADER)}")
                )
            parsed = _parse_row(reader.line_num, dict(zip(HEADER, (c.strip() for c in cells), strict=True)))
            if parsed.is_err:
                return Result.err(parsed.unwrap_err())
            rows.append(parsed.unwrap())
        return Result.ok(rows)
