from sqlalchemy.orm import Session
from kohle.domain.models import Account, Operation
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.operations import ListOperations
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
    operation_tracking_res = ListOperations(session).execute()
    assert operation_tracking_res.is_ok
    operation_tracking = operation_tracking_res.unwrap()
    assert isinstance(operation_tracking, list)
    assert len(operation_tracking) == 1
    assert isinstance(operation_tracking[0], Operation)
    assert operation_tracking == [Operation(group_id=1, entity_type="accounts", entity_id=1, action="create")]


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

