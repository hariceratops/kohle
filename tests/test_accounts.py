from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from kohle.domain.domain_errors import (
    DuplicateAccountName,
    DuplicateIBAN,
    EmptyAccountName,
    ParentAccountNotFound,
    ParentHasPostings,
)
from kohle.domain.models import Account, AccountType, Operation
from kohle.use_cases.accounts import AddAccount, ListAccount, ListChildAccounts
from kohle.use_cases.journal import RecordSimpleEntry
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


def test_an_account_with_postings_cannot_become_a_parent(session: Session) -> None:
    """The postings would be stranded on a non-leaf: it could no longer be
    posted to, and nothing could move them onto the new child."""
    AddAccount(session).execute("Cash", AccountType.asset)
    AddAccount(session).execute("Food", AccountType.expense)
    RecordSimpleEntry(session).execute(date(2026, 3, 2), "Rewe", Decimal(10), "Cash", "Food")

    result = AddAccount(session).execute("Envelope", AccountType.asset, None, "Cash")

    assert result.is_err
    err = result.unwrap_err()
    assert isinstance(err, ParentHasPostings)
    assert "Cash" in str(err)
    assert [a.name for a in ListAccount(session).execute().unwrap()] == ["Cash", "Food"]


def test_an_account_without_postings_can_still_become_a_parent(session: Session) -> None:
    AddAccount(session).execute("Cash", AccountType.asset)
    AddAccount(session).execute("Food", AccountType.expense)
    RecordSimpleEntry(session).execute(date(2026, 3, 2), "Rewe", Decimal(10), "Cash", "Food")
    AddAccount(session).execute("Wallet", AccountType.asset)

    assert AddAccount(session).execute("Envelope", AccountType.asset, None, "Wallet").is_ok
