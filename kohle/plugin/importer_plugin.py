from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from kohle.core.result import Result


class ImportError(Exception):
    """Base of every importer failure. Its `__str__` is what the user sees after `Error: `."""


class StatementUnreadable(ImportError):
    """The statement file could not be opened or decoded. `path` is the file, `reason` the cause."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__()
        self.path = path
        self.reason = reason

    def __str__(self) -> str:
        return f"Cannot read statement {self.path}: {self.reason}"


# Counterparty is two plain fields rather than services' `Counterparty`: this
# module must stay a leaf, or every plugin would depend on the services layer.
# No defaults, so a plugin with no counterparty data says so explicitly.
@dataclass(frozen=True, slots=True, kw_only=True)
class CashRow:
    """A cash movement: quantity in the base currency at price 1.

    `amount` is signed; negative is money leaving the imported account.
    `reference` identifies the row within its statement and must be unique;
    a format with no native one derives it from row content inside the plugin.
    """

    entry_date: date
    """The booking or value date; the plugin chooses."""
    reference: str
    """Unique per row within the statement; a repeat rejects the import. A row whose reference was already imported into the same cash account is skipped."""
    description: str
    """Free text from the statement."""
    amount: Decimal
    """Signed; negative is money leaving the imported account."""
    counterparty_name: str | None
    """Who the other side was, or `None` if the format does not say."""
    counterparty_iban: str | None
    """The other side's IBAN, not the imported account's, or `None` if the format does not say."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SecurityRow:
    """A trade: `quantity` of an instrument at `unit_price` base currency each.

    `quantity` is signed like `CashRow.amount`, from the instrument account's
    side: positive is a buy, negative a sell. The cash leg is derived as
    |quantity| * unit_price, so an unbalanced trade is not expressible.
    """

    entry_date: date
    """The trade date; the plugin chooses."""
    reference: str
    """Unique per row within the statement, with the same dedup rule as `CashRow.reference`."""
    description: str
    """Free text describing the trade."""
    instrument_identifier: str
    """The `identifier` of a security unit that must already exist in the ledger."""
    quantity: Decimal
    """Signed; positive is a buy, negative a sell."""
    unit_price: Decimal
    """Base currency per unit; finite and above zero."""


StatementRow = CashRow | SecurityRow


class StatementImporterPlugin(ABC):
    """A statement file becomes one typed row per statement line, in order.

    `import_statement` holds no state between calls. An unreadable or
    unparseable file is returned as an `ImportError`, never raised.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The name typed as `PLUGIN` in `import-statement`. Unique among importer plugins."""

    @abstractmethod
    def import_statement(self, statement_path: str) -> Result[list[StatementRow], ImportError]:
        """Read the file at `statement_path` and return its rows in statement order.

        Return `Result.err` with an `ImportError` subclass for a file that
        cannot be read or parsed; nothing is imported then.
        """
