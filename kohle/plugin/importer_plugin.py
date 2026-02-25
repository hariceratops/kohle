from abc import ABC, abstractmethod
import pandas as pd
from kohle.core.result import Result


class ImportError(Exception):
    pass


class StatementImporterPlugin(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def import_statement(self, statement_path: str) -> Result[pd.DataFrame, ImportError]:
        pass
