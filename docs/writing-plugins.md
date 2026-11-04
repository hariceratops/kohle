# Writing plugins

kohle has two kinds of plugin: a statement importer, which turns a bank or
broker file into rows, and a price plugin, which looks up the latest close of
a security. Both are ordinary Python classes found through the `kohle.plugins`
entry-point group, so adding one needs no change to kohle.

The contract sections below are generated from the docstrings in
[`importer_plugin.py`](https://github.com/hariceratops/kohle/blob/main/kohle/plugin/importer_plugin.py)
and
[`price_plugin.py`](https://github.com/hariceratops/kohle/blob/main/kohle/plugin/price_plugin.py)
when the site is built. On GitHub they show only as directives; read those two
files instead.

## Registering a plugin

Declare the class under `kohle.plugins` in the plugin package's
`pyproject.toml`. The entry-point name is only a label. The name a user types
is the `name` property of the class, and it must be unique among plugins of the
same kind.

```toml
[project]
name = "kohle-example-plugins"
version = "0.1.0"
dependencies = ["kohle"]

[project.entry-points."kohle.plugins"]
example-credit-union = "kohle_example_plugins.importer:CreditUnionImporter"
example-prices = "kohle_example_plugins.prices:ExamplePriceFetcher"
```

Install the package into the environment that runs `kohle-cli` and the plugin
is found on the next command. A class that is neither a
`StatementImporterPlugin` nor a `PriceFetcherPlugin` is an error, and so is a
name used twice within one kind.

Every command that uses plugins loads every entry point, so importing the
module and constructing the class must not do I/O or read configuration.

Start the class docstring with one paragraph saying what the plugin accepts.
The [Installed plugins](plugins.md) page shows exactly that paragraph.

## Writing an importer

A statement importer reads one file and returns one row per statement line, in
order.

::: kohle.plugin.importer_plugin.StatementImporterPlugin

::: kohle.plugin.importer_plugin.CashRow

::: kohle.plugin.importer_plugin.SecurityRow

::: kohle.plugin.importer_plugin.StatementUnreadable

### What kohle does with the rows

- `import-statement PLUGIN CASH_ACCOUNT [INSTRUMENT_ACCOUNT] FILE` posts one
  balanced entry per row.
- A `reference` is scoped to the cash account, so importing the same file
  again posts nothing. A reference repeated inside one statement rejects the
  whole import before anything is written.
- A statement with trades needs the `INSTRUMENT_ACCOUNT` argument, and each
  `instrument_identifier` must already exist as a security unit. Unknown
  identifiers are all named in one error and nothing is imported.
- A trade has no cash amount: the cash leg is `abs(quantity) * unit_price`. A
  row with an empty identifier, a zero quantity or a price that is missing,
  zero, negative or not finite rejects the whole import.
- Cash rows go through the classification rules. Trades do not.
- Fields have no defaults, so a format with no counterparty data passes `None`
  explicitly. Omitting a field is a `TypeError`.

### Errors

Return errors; do not raise them. Subclass `ImportError` from
`kohle.plugin.importer_plugin` for each way your format can be wrong, and give
it a `__str__` that says what is wrong and where, because that text is shown to
the user. Use `Result.ok(value)` for success and `Result.err(error)` for
failure.

### An example importer

This importer reads a fictional credit union export, a semicolon-separated file
with the header `id;date;text;amount`. The statement's own `id` is the
reference.

```python
import csv
from datetime import date
from decimal import Decimal, InvalidOperation

from kohle.core.result import Result
from kohle.plugin.importer_plugin import (
    CashRow,
    ImportError,
    StatementImporterPlugin,
    StatementRow,
    StatementUnreadable,
)


class BadAmount(ImportError):
    def __init__(self, line: int, text: str) -> None:
        super().__init__()
        self.line = line
        self.text = text

    def __str__(self) -> str:
        return f"Line {self.line}: {self.text!r} is not an amount"


class CreditUnionImporter(StatementImporterPlugin):
    """A fictional credit union export: semicolon-separated, header `id;date;text;amount`, EUR."""

    @property
    def name(self) -> str:
        return "example-credit-union"

    def import_statement(self, statement_path: str) -> Result[list[StatementRow], ImportError]:
        try:
            with open(statement_path, encoding="utf-8", newline="") as statement:
                lines = list(csv.DictReader(statement, delimiter=";"))
        except (OSError, UnicodeDecodeError, csv.Error) as e:
            return Result.err(StatementUnreadable(statement_path, str(e)))

        rows: list[StatementRow] = []
        for number, line in enumerate(lines, start=2):
            try:
                amount = Decimal(line["amount"])
            except InvalidOperation:
                return Result.err(BadAmount(number, line["amount"]))
            rows.append(
                CashRow(
                    entry_date=date.fromisoformat(line["date"]),
                    reference=line["id"],
                    description=line["text"],
                    amount=amount,
                    counterparty_name=None,
                    counterparty_iban=None,
                )
            )
        return Result.ok(rows)
```

The example leaves out checks that a real importer needs, such as a missing
column or a malformed date. Each should be an `ImportError` of its own.

## Writing a price plugin

A price plugin answers one question: the latest finished daily close for each
symbol it is asked about. A security unit is bound to one plugin and one symbol
with `set-price-source`, and `fetch-prices` asks each plugin once for the
symbols bound to it. Reports never call a plugin.

::: kohle.plugin.price_plugin.PriceFetcherPlugin

::: kohle.plugin.price_plugin.Close

::: kohle.plugin.price_plugin.Unavailable

::: kohle.plugin.price_plugin.UnavailableReason

::: kohle.plugin.price_plugin.MissingEnvironmentVariable

### What kohle does with the results

- Every close is checked before it is stored: the price must be finite and
  above zero, the date must not be in the future, and the currency must be the
  base currency. A rejected close leaves only that symbol's units unpriced.
- A date is stored once, so fetching again is a no-op.
- There is no fallback to another plugin. To change a unit's source, bind it
  again.

### An example price plugin

This plugin serves a fixed table, in the order of the symbols it is given. Real
plugins read a file or call a service, but only inside
`fetch_latest_closes`.

```python
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from kohle.core.result import Result
from kohle.plugin.price_plugin import (
    Close,
    PriceFetcherPlugin,
    PriceFetchError,
    PriceResult,
    Unavailable,
    UnavailableReason,
)

CLOSES = {"ACME": (date(2026, 6, 16), Decimal("12.40"))}


class ExamplePriceFetcher(PriceFetcherPlugin):
    """Symbols from a fixed in-memory table of fictional closes, quoted in EUR."""

    @property
    def name(self) -> str:
        return "example-prices"

    def fetch_latest_closes(
        self, symbols: Sequence[str]
    ) -> Result[dict[str, PriceResult], PriceFetchError]:
        results: dict[str, PriceResult] = {}
        for symbol in symbols:
            if symbol in CLOSES:
                price_date, price = CLOSES[symbol]
                results[symbol] = Close(price_date=price_date, price=price, currency="EUR")
            else:
                results[symbol] = Unavailable(reason=UnavailableReason.no_symbol, detail="not in the table")
        return Result.ok(results)
```

Bind a unit to it, once the package is installed, with
`kohle-cli set-price-source ACME example-prices ACME`.
