from sqlalchemy.orm import Session
from kohle.infrastructure.uow import UnitOfWork
from kohle.services.account_services import (
    add_account_service,
    get_account_by_name_service,
)
from kohle.domain.domain_errors import (
    DuplicateAccountName,
    DuplicateIBAN,
    AccountNotFoundError,
)


def test_add_account_success(session: Session) -> None:
    uow = UnitOfWork(session)
    result = add_account_service(uow, "Alice", "DE123")
    assert result.is_ok
    assert isinstance(result.unwrap(), int)


def test_add_account_duplicate_name(session: Session) -> None:
    uow = UnitOfWork(session)
    add_account_service(uow, "Alice", "DE123")
    result = add_account_service(uow, "Alice", "DE999")
    assert result.is_err
    assert isinstance(result.unwrap_err(), DuplicateAccountName)


def test_add_account_duplicate_iban(session: Session) -> None:
    uow = UnitOfWork(session)
    add_account_service(uow, "Alice", "DE123")
    result = add_account_service(uow, "Bob", "DE123")
    assert result.is_err
    assert isinstance(result.unwrap_err(), DuplicateIBAN)


def test_get_account_found(session: Session) -> None:
    uow = UnitOfWork(session)
    add_account_service(uow, "Alice", "DE123")
    result = get_account_by_name_service(uow, "Alice")
    assert result.is_ok
    account = result.unwrap()
    assert account.name == "Alice"
    assert account.iban == "DE123"


def test_get_account_not_found(session: Session) -> None:
    uow = UnitOfWork(session)
    result = get_account_by_name_service(uow, "Missing")
    assert result.is_err
    assert isinstance(result.unwrap_err(), AccountNotFoundError)

