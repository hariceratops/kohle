from abc import ABC, abstractmethod

import pandas as pd

from kohle.core.result import Result


class ImportError(Exception):
    pass


class StatementImporterPlugin(ABC):
    """A statement file becomes one row per cash movement.

    `import_statement` returns a frame carrying exactly these columns:

    | column              | dtype    | meaning                                  |
    |---------------------|----------|------------------------------------------|
    | `description`       | string   | free text from the statement             |
    | `amount`            | float    | signed; negative is money leaving        |
    | `date`              | datetime | booking or value date, plugin's choice   |
    | `counterparty_name` | string   | who the other side was                   |
    | `counterparty_iban` | string   | the other side's IBAN                    |

    A plugin whose format carries no counterparty at all still declares the
    column, empty:

        df.assign(counterparty_iban=pd.Series(pd.NA, index=df.index, dtype="string"))

    Absence per row is normal — an ATM withdrawal has no beneficiary — and is
    stored as NULL. Absence of the *column* is a hard failure, named by
    `DataframeMissingColumn` before a single row is touched: a counterparty
    that silently goes missing is what makes a classification rule stop
    matching with nothing anywhere saying why.

    The `string` dtypes are part of the contract, not a formality: `read_csv`
    types a text column that is empty on every row as `float64`, so a statement
    with no counterparty data anywhere fails the schema check unless the plugin
    casts. `.astype("string")` is stable under all-NA.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def import_statement(self, statement_path: str) -> Result[pd.DataFrame, ImportError]:
        pass
