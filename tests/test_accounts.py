from sqlalchemy.orm import Session
from kohle.infrastructure.uow import UnitOfWork
from kohle.use_cases.accounts import add_account
from kohle.domain.domain_errors import (
    EmptyAccountName,
    EmptyIBAN,
    DuplicateAccountName,
    DuplicateIBAN,
)


def test_add_account_success(session: Session) -> None:
    uow = UnitOfWork(session)
    result = add_account(uow, "Alice", "DE123")
    assert result.is_ok
    assert isinstance(result.unwrap(), int)


def test_add_account_empty_name(session: Session) -> None:
    uow = UnitOfWork(session)
    result = add_account(uow, "   ", "DE123")
    assert result.is_err
    assert isinstance(result.unwrap_err(), EmptyAccountName)


def test_add_account_empty_iban(session: Session) -> None:
    uow = UnitOfWork(session)
    result = add_account(uow, "Alice", "")
    assert result.is_err
    assert isinstance(result.unwrap_err(), EmptyIBAN)


def test_add_account_duplicate_name(session: Session) -> None:
    uow = UnitOfWork(session)
    add_account(uow, "Alice", "DE123")
    result = add_account(uow, "Alice", "DE999")
    assert result.is_err
    assert isinstance(result.unwrap_err(), DuplicateAccountName)


def test_add_account_duplicate_iban(session: Session) -> None:
    uow = UnitOfWork(session)
    add_account(uow, "Alice", "DE123")
    result = add_account(uow, "Bob", "DE123")
    assert result.is_err
    assert isinstance(result.unwrap_err(), DuplicateIBAN)
