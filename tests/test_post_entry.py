"""Layer 3 — use-case tests against the `session` fixture.

The entry-posting use case behind `record` (issues 001, 004).

The point of these is that the CLI adds no validation: balance-by-value and
leaf-only posting are enforced once, in the use case, so a TUI or any other
frontend gets them free. Assertions are on `Result` and on domain error
types, matching the existing use-case tests.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from kohle.domain.domain_errors import AccountNotFoundError, PostingToNonLeafAccount
from kohle.domain.models import AccountType
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.journal import BASE_CURRENCY, RecordSimpleEntry
from kohle.use_cases.units import ListUnits


def test_base_currency_entry_posts_and_balances(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    AddAccount(session).execute("Unallocated", AccountType.asset)

    result = RecordSimpleEntry(session).execute(
        date(2026, 3, 1), "Withdraw cash", Decimal(200), "Checking", "Unallocated"
    )

    assert result.is_ok
    entry = result.unwrap()
    assert len(entry.lines) == 2
    debits = sum((line.value for line in entry.lines if line.is_debit), Decimal(0))
    credits = sum((line.value for line in entry.lines if not line.is_debit), Decimal(0))
    assert debits == credits == Decimal(200)


def test_from_is_credited_to_is_debited_at_unit_price_one(session: Session) -> None:
    checking = AddAccount(session).execute("Checking", AccountType.asset, "DE1").unwrap()
    unallocated = AddAccount(session).execute("Unallocated", AccountType.asset).unwrap()

    entry = RecordSimpleEntry(session).execute(
        date(2026, 3, 1), "Withdraw cash", Decimal(200), "Checking", "Unallocated"
    ).unwrap()

    debit_line = next(line for line in entry.lines if line.is_debit)
    credit_line = next(line for line in entry.lines if not line.is_debit)
    assert debit_line.account_id == unallocated.id
    assert credit_line.account_id == checking.id
    assert debit_line.unit_price == Decimal(1)
    assert credit_line.unit_price == Decimal(1)


def test_reference_is_system_generated_and_differs_between_entries(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    AddAccount(session).execute("Unallocated", AccountType.asset)

    first = RecordSimpleEntry(session).execute(
        date(2026, 3, 1), "Withdraw cash", Decimal(200), "Checking", "Unallocated"
    ).unwrap()
    second = RecordSimpleEntry(session).execute(
        date(2026, 3, 1), "Withdraw cash", Decimal(200), "Checking", "Unallocated"
    ).unwrap()

    assert first.reference
    assert second.reference
    assert first.reference != second.reference


def test_unknown_account_returns_account_not_found(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")

    result = RecordSimpleEntry(session).execute(
        date(2026, 3, 1), "Withdraw cash", Decimal(200), "Checking", "Nope"
    )

    assert result.is_err
    assert isinstance(result.unwrap_err(), AccountNotFoundError)


def test_posting_to_non_leaf_account_rejected(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    AddAccount(session).execute("Cash", AccountType.asset)
    AddAccount(session).execute("Unallocated", AccountType.asset, None, "Cash")

    result = RecordSimpleEntry(session).execute(
        date(2026, 3, 1), "Withdraw cash", Decimal(200), "Checking", "Cash"
    )

    assert result.is_err
    assert isinstance(result.unwrap_err(), PostingToNonLeafAccount)


def test_base_currency_is_created_on_first_use(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    AddAccount(session).execute("Unallocated", AccountType.asset)

    result = RecordSimpleEntry(session).execute(
        date(2026, 3, 1), "Withdraw cash", Decimal(200), "Checking", "Unallocated"
    )

    assert result.is_ok
    units = ListUnits(session).execute().unwrap()
    eur_id = next(u.id for u in units if u.identifier == BASE_CURRENCY)
    assert all(line.unit_id == eur_id for line in result.unwrap().lines)


def test_cross_unit_placeholder(session: Session) -> None:
    # Cross-unit, issue 004 — the direction is the whole point
    # TODO: a purchase (units arrive via the debit side) posts correctly
    # TODO: a sale (units leave via the credit side) posts correctly and is
    #       reachable without record-split
    # TODO: both balance by value: the base-currency side is quantity x price
    # TODO: naming a base-currency unit on either side is a domain error,
    #       with or without a price
    # TODO: a sale of a unit never bought is posted, not rejected — the
    #       ledger records what happened
    assert True
