class CategoryError(Exception):
    pass


class EmptyCategoryName(CategoryError):
    def __str__(self) -> str:
        return "Category name cannot be empty"


class DuplicateCategory(CategoryError):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

    def __str__(self) -> str:
        return "Category already exists"


class AccountError(Exception):
    pass


class AccountNotFoundError(AccountError):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

    def __str__(self) -> str:
        return f"Account name {self.name} cannot be empty"


class EmptyAccountName(AccountError):
    def __str__(self) -> str:
        return "Account name cannot be empty"


class EmptyIBAN(AccountError):
    def __str__(self) -> str:
        return "IBAN name cannot be empty"


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


class TransactionError(Exception):
    def __str__(self) -> str:
        return ""


class DuplicationTransactionError(TransactionError):
    def __str__(self) -> str:
        return "Duplicate transactions found"


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

QueryTransactionByPeriodError = InvalidDateError | TransactionError | EndDatePrecedesStartDateError | AccountNotFoundError


