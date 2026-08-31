from dataclasses import dataclass


class AccountError(Exception):
    pass


class AccountNotFoundError(AccountError):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

    def __str__(self) -> str:
        return f"Account {self.name} not found"


class EmptyAccountName(AccountError):
    def __str__(self) -> str:
        return "Account name cannot be empty"


class DuplicateAccountName(AccountError):
    def __init__(self, account_name: str) -> None:
        super().__init__()
        self.account_name = account_name

    def __str__(self) -> str:
        return f"Account {self.account_name} already exists"


class DuplicateIBAN(AccountError):
    def __init__(self, iban: str) -> None:
        super().__init__()
        self.iban = iban

    def __str__(self) -> str:
        return f"IBAN {self.iban} already exists"


class ParentAccountNotFound(AccountError):
    def __init__(self, parent_name: str) -> None:
        super().__init__()
        self.parent_name = parent_name

    def __str__(self) -> str:
        return f"Parent account {self.parent_name} not found"


class UnitError(Exception):
    pass


class UnitNotFoundError(UnitError):
    def __init__(self, identifier: str) -> None:
        super().__init__()
        self.identifier = identifier

    def __str__(self) -> str:
        return f"Unit {self.identifier} not found"


class DuplicateUnit(UnitError):
    def __init__(self, identifier: str) -> None:
        super().__init__()
        self.identifier = identifier

    def __str__(self) -> str:
        return f"Unit {self.identifier} already exists"


class EmptyUnitIdentifier(UnitError):
    def __str__(self) -> str:
        return "Unit identifier cannot be empty"


class JournalError(Exception):
    pass


class DuplicateJournalEntry(JournalError):
    def __init__(self, reference: str) -> None:
        super().__init__()
        self.reference = reference

    def __str__(self) -> str:
        return f"Journal entry {self.reference} already exists"


class UnbalancedEntry(JournalError):
    def __init__(self, debit_total, credit_total) -> None:
        super().__init__()
        self.debit_total = debit_total
        self.credit_total = credit_total

    def __str__(self) -> str:
        return f"Entry does not balance: debits {self.debit_total} against credits {self.credit_total}"


class PostingToNonLeafAccount(JournalError):
    """Parent balances are the sum of their children, so a posting that lands on
    a parent silently breaks every rollup."""

    def __init__(self, account_id: int) -> None:
        super().__init__()
        self.account_id = account_id

    def __str__(self) -> str:
        return f"Account id {self.account_id} has children and cannot be posted to directly"


class EmptyEntry(JournalError):
    def __str__(self) -> str:
        return "Journal entry must have at least two lines"


class InvalidDateError(Exception):
    def __init__(self, date_str: str) -> None:
        super().__init__()
        self.date_str = date_str

    def __str__(self) -> str:
        return f"Unable to parse date from str {self.date_str}"


class EndDatePrecedesStartDateError(Exception):
    def __init__(self, start_date: str, end_date: str) -> None:
        super().__init__()
        self.start_date = start_date
        self.end_date = end_date

    def __str__(self) -> str:
        return f"End date {self.end_date} precedes start_date {self.start_date}"


@dataclass
class DataframeMissingColumn:
    columns: list[str]


@dataclass
class DataframeColumnTypeMismatch:
    mismatches: dict[str, str]  # column -> actual dtype


DataframeValidationError = DataframeMissingColumn | DataframeColumnTypeMismatch

QueryJournalByPeriodError = \
        InvalidDateError | \
        JournalError | \
        EndDatePrecedesStartDateError | \
        AccountNotFoundError

ImportStatementError = \
        AccountNotFoundError | \
        JournalError | \
        UnitError | \
        DataframeValidationError
