from sqlalchemy.orm import Session

from kohle.domain.domain_errors import (
    DuplicateAccountName,
    DuplicateIBAN,
    EmptyAccountName,
    ParentAccountNotFound,
)
from kohle.domain.models import Account, AccountType, Operation
from kohle.use_cases.accounts import AddAccount, ListChildAccounts
from kohle.use_cases.operations import ListOperations


def test_add_account_success(session: Session) -> None:
    result = AddAccount(session).execute("Alice", AccountType.asset, "DE123")
    assert result.is_ok
    account = result.unwrap()
    assert isinstance(account, Account)
    assert account.name == "Alice"
    assert account.iban == "DE123"

    operations = ListOperations(session).execute()
    assert operations.is_ok
    assert operations.unwrap() == [
        Operation(group_id=1, entity_type="accounts", entity_id=1, action="create")
    ]


def test_add_expense_account_without_iban(session: Session) -> None:
    result = AddAccount(session).execute("Groceries", AccountType.expense)
    assert result.is_ok
    assert result.unwrap().iban is None


def test_add_account_empty_name(session: Session) -> None:
    result = AddAccount(session).execute("   ", AccountType.asset, "DE123")
    assert result.is_err
    assert isinstance(result.unwrap_err(), EmptyAccountName)


def test_add_account_duplicate_name(session: Session) -> None:
    AddAccount(session).execute("Alice", AccountType.asset, "DE999")
    result = AddAccount(session).execute("Alice", AccountType.asset, "DE998")
    assert result.is_err
    assert isinstance(result.unwrap_err(), DuplicateAccountName)


def test_add_account_duplicate_iban(session: Session) -> None:
    AddAccount(session).execute("Bob", AccountType.asset, "DE123")
    result = AddAccount(session).execute("Carol", AccountType.asset, "DE123")
    assert result.is_err
    assert isinstance(result.unwrap_err(), DuplicateIBAN)


def test_add_virtual_account_under_parent(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    result = AddAccount(session).execute("Holiday", AccountType.asset, None, "Checking")
    assert result.is_ok

    children = ListChildAccounts(session).execute("Checking")
    assert children.is_ok
    assert [c.name for c in children.unwrap()] == ["Holiday"]


def test_add_account_unknown_parent(session: Session) -> None:
    result = AddAccount(session).execute("Holiday", AccountType.asset, None, "Nope")
    assert result.is_err
    assert isinstance(result.unwrap_err(), ParentAccountNotFound)
