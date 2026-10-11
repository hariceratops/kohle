from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from kohle.core.result import Result


class PriceFetchError(Exception):
    pass


class MissingEnvironmentVariable(PriceFetchError):
    def __init__(self, variable: str) -> None:
        super().__init__()
        self.variable = variable

    def __str__(self) -> str:
        return f"{self.variable} is not set"


class UnavailableReason(Enum):
    no_symbol = "no_symbol"
    not_covered = "not_covered"
    transient = "transient"


# No defaults: a plugin states the currency every time, so a symbol bound as an
# EUR assertion has a visible line in the plugin that makes it.
@dataclass(frozen=True, slots=True, kw_only=True)
class Close:
    """A finished daily close. `currency` is the plugin's claim about its data;
    core compares it with the base currency."""

    price_date: date
    price: Decimal
    currency: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Unavailable:
    """No close for one symbol. `detail` carries the source's own words, so a
    permanent condition reported as `transient` stays diagnosable."""

    reason: UnavailableReason
    detail: str

    def __str__(self) -> str:
        return f"{self.reason.value}: {self.detail}"


PriceResult = Close | Unavailable


class PriceFetcherPlugin(ABC):
    """The latest finished daily close for each requested symbol.

    Rules:
    - `Err` means the plugin as a whole could not run (missing configuration,
      unreachable source, unreadable file). Anything about one symbol is an
      `Unavailable` value.
    - Expected failures are returned, never raised. A plugin bug is not caught.
    - Only finished closes; a trading day in progress is never returned.
    - No I/O or configuration reads in `__init__` or at import: every
      plugin-using command imports every entry point, and `set-price-source`
      instantiates every price plugin to learn its name.
    - No state between calls.
    - Requests are spent in the order given. A plugin that cannot serve every
      symbol in one call works through `symbols` in order and returns
      `Unavailable(transient)` for each one it did not reach. It never
      re-sorts.
    - The result is keyed by the symbol exactly as requested.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def fetch_latest_closes(
        self, symbols: Sequence[str]
    ) -> Result[dict[str, PriceResult], PriceFetchError]:
        pass
