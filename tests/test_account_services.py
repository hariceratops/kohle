from sqlalchemy.orm import Session

from kohle.domain.domain_errors import (
    AccountNotFoundError,
    DuplicateAccountName,
    DuplicateIBAN,
)
from kohle.domain.models import Account, AccountType
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.account_services import (
    account_has_children_service,
    add_account_service,
    get_account_by_iban_service,
    get_account_by_name_service,
    list_child_accounts_service,
)


def test_add_account_success(session: Session) -> None:
    ctx = DbTransactionContext(session)
    result = add_account_service(ctx, "Alice", AccountType.asset, "DE123")
    assert result.is_ok
    account = result.unwrap()
    assert isinstance(account, Account)
    assert account.name == "Alice"
    assert account.iban == "DE123"
    assert account.type == AccountType.asset


def test_add_account_without_iban(session: Session) -> None:
    ctx = DbTransactionContext(session)
    result = add_account_service(ctx, "Groceries", AccountType.expense)
    assert result.is_ok
    assert result.unwrap().iban is None


def test_two_accounts_without_iban_do_not_collide(session: Session) -> None:
    ctx = DbTransactionContext(session)
    assert add_account_service(ctx, "Groceries", AccountType.expense).is_ok
    assert add_account_service(ctx, "Rent", AccountType.expense).is_ok


def test_add_account_duplicate_name(session: Session) -> None:
    ctx = DbTransactionContext(session)
    add_account_service(ctx, "Alice", AccountType.asset, "DE123")
    result = add_account_service(ctx, "Alice", AccountType.asset, "DE999")
    assert result.is_err
    assert isinstance(result.unwrap_err(), DuplicateAccountName)


def test_child_name_collides_with_any_other_account(session: Session) -> None:
    """Names are globally unique until accounts are addressable by qualified
    path, so two parents cannot each hold a child of the same name."""
    ctx = DbTransactionContext(session)
    checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap()
    savings = add_account_service(ctx, "Savings", AccountType.asset, "DE2").unwrap()
    assert add_account_service(ctx, "Holiday", AccountType.asset, None, checking.id).is_ok
    result = add_account_service(ctx, "Holiday", AccountType.asset, None, savings.id)
    assert result.is_err
    assert isinstance(result.unwrap_err(), DuplicateAccountName)


def test_add_account_duplicate_iban(session: Session) -> None:
    ctx = DbTransactionContext(session)
    add_account_service(ctx, "Alice", AccountType.asset, "DE123")
    result = add_account_service(ctx, "Bob", AccountType.asset, "DE123")
    assert result.is_err
    assert isinstance(result.unwrap_err(), DuplicateIBAN)


def test_get_account_found(session: Session) -> None:
    ctx = DbTransactionContext(session)
    add_account_service(ctx, "Alice", AccountType.asset, "DE123")
    result = get_account_by_name_service(ctx, "Alice")
    assert result.is_ok
    assert result.unwrap().iban == "DE123"


def test_get_account_not_found(session: Session) -> None:
    ctx = DbTransactionContext(session)
    result = get_account_by_name_service(ctx, "Missing")
    assert result.is_err
    assert isinstance(result.unwrap_err(), AccountNotFoundError)


def test_get_account_by_iban(session: Session) -> None:
    ctx = DbTransactionContext(session)
    add_account_service(ctx, "Alice", AccountType.asset, "DE123")
    result = get_account_by_iban_service(ctx, "DE123")
    assert result.is_ok
    assert result.unwrap().name == "Alice"


def test_children_and_leafness(session: Session) -> None:
    ctx = DbTransactionContext(session)
    parent = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap()
    assert account_has_children_service(ctx, parent.id).unwrap() is False

    add_account_service(ctx, "Holiday", AccountType.asset, None, parent.id)
    assert account_has_children_service(ctx, parent.id).unwrap() is True

    children = list_child_accounts_service(ctx, parent.id)
    assert children.is_ok
    assert [c.name for c in children.unwrap()] == ["Holiday"]
