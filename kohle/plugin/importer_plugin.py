from abc import ABC, abstractmethod
import pandas as pd


class StatementImporterPlugin(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def import_statement(self, statement_path: str) -> pd.DataFrame:
        pass
