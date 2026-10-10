from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from kohle.core.result import Result


class ImportError(Exception):
    pass


class StatementUnreadable(ImportError):
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
    reference: str
    description: str
    amount: Decimal
    counterparty_name: str | None
    counterparty_iban: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class SecurityRow:
    """A trade: `quantity` of an instrument at `unit_price` base currency each.

    `quantity` is signed like `CashRow.amount`, from the instrument account's
    side: positive is a buy, negative a sell. The cash leg is derived as
    |quantity| * unit_price, so an unbalanced trade is not expressible.
    """

    entry_date: date
    reference: str
    description: str
    instrument_identifier: str
    quantity: Decimal
    unit_price: Decimal


StatementRow = CashRow | SecurityRow


class StatementImporterPlugin(ABC):
    """A statement file becomes one typed row per statement line, in order.

    `import_statement` holds no state between calls. An unreadable or
    unparseable file is returned as an `ImportError`, never raised.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def import_statement(self, statement_path: str) -> Result[list[StatementRow], ImportError]:
        pass
