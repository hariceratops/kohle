from sqlalchemy.orm import Session
from kohle.domain.models import Account
from kohle.use_cases.accounts import AddAccount
from kohle.domain.domain_errors import (
    EmptyAccountName,
    EmptyIBAN,
    DuplicateAccountName,
    DuplicateIBAN,
)


def test_add_account_success(session: Session) -> None:
    add_account = AddAccount(session)
    result = add_account.execute("Alice", "DE123")
    assert result.is_ok
    unwrapped_res = result.unwrap()
    assert isinstance(unwrapped_res, Account)
    assert unwrapped_res.name == "Alice"
    assert unwrapped_res.iban == "DE123"


def test_add_account_empty_name(session: Session) -> None:
    add_account = AddAccount(session)
    result = add_account.execute("   ", "DE123")
    assert result.is_err
    assert isinstance(result.unwrap_err(), EmptyAccountName)


def test_add_account_empty_iban(session: Session) -> None:
    add_account = AddAccount(session)
    result = add_account.execute("Alice", "")
    assert result.is_err
    assert isinstance(result.unwrap_err(), EmptyIBAN)


def test_add_account_duplicate_name(session: Session) -> None:
    add_account = AddAccount(session)
    result = add_account.execute("Alice", "DE999")
    result = add_account.execute("Alice", "DE998")
    assert result.is_err
    assert isinstance(result.unwrap_err(), DuplicateAccountName)


def test_add_account_duplicate_iban(session: Session) -> None:
    add_account = AddAccount(session)
    result = add_account.execute("Bob", "DE123")
    result = add_account.execute("Bob", "DE123")
    assert result.is_err
    assert isinstance(result.unwrap_err(), DuplicateIBAN)

