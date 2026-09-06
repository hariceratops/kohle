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

from kohle.domain.domain_errors import (
    AccountNotFoundError,
    BaseCurrencyAsCrossUnit,
    PostingToNonLeafAccount,
    UnitNotFoundError,
)
from kohle.domain.models import AccountType, UnitKind
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.journal import BASE_CURRENCY, CrossUnitLine, RecordSimpleEntry
from kohle.use_cases.units import AddUnit, ListUnits


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


def test_cross_unit_purchase_posts_units_on_debit_side(session: Session) -> None:
    checking = AddAccount(session).execute("Checking", AccountType.asset, "DE1").unwrap()
    broker = AddAccount(session).execute("Broker", AccountType.asset).unwrap()
    AddUnit(session).execute("IE00B4L5Y983", "Core MSCI World", UnitKind.security)

    result = RecordSimpleEntry(session).execute(
        date(2026, 3, 6),
        "Buy ETF",
        Decimal(10),
        "Checking",
        "Broker",
        CrossUnitLine("IE00B4L5Y983", Decimal(100), is_debit=True),
    )

    assert result.is_ok
    entry = result.unwrap()
    debit_line = next(line for line in entry.lines if line.is_debit)
    credit_line = next(line for line in entry.lines if not line.is_debit)
    assert debit_line.account_id == broker.id
    assert debit_line.quantity == Decimal(10)
    assert debit_line.unit_price == Decimal(100)
    assert credit_line.account_id == checking.id
    assert credit_line.quantity == Decimal(1000)
    assert credit_line.unit_price == Decimal(1)


def test_cross_unit_sale_posts_units_leaving_on_credit_side(session: Session) -> None:
    broker = AddAccount(session).execute("Broker", AccountType.asset).unwrap()
    checking = AddAccount(session).execute("Checking", AccountType.asset, "DE1").unwrap()
    AddUnit(session).execute("IE00B4L5Y983", "Core MSCI World", UnitKind.security)

    result = RecordSimpleEntry(session).execute(
        date(2026, 4, 20),
        "Sell ETF",
        Decimal(10),
        "Broker",
        "Checking",
        CrossUnitLine("IE00B4L5Y983", Decimal(110), is_debit=False),
    )

    assert result.is_ok
    entry = result.unwrap()
    credit_line = next(line for line in entry.lines if not line.is_debit)
    debit_line = next(line for line in entry.lines if line.is_debit)
    assert credit_line.account_id == broker.id
    assert credit_line.quantity == Decimal(10)
    assert credit_line.unit_price == Decimal(110)
    assert debit_line.account_id == checking.id
    assert debit_line.quantity == Decimal(1100)
    assert debit_line.unit_price == Decimal(1)


def test_sale_of_a_unit_never_bought_is_posted_not_rejected(session: Session) -> None:
    # The ledger records what happened; it does not track prior holdings, so
    # a sale with no matching purchase is not special-cased or rejected.
    AddAccount(session).execute("Broker", AccountType.asset)
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    AddUnit(session).execute("IE00B4L5Y983", "Core MSCI World", UnitKind.security)

    result = RecordSimpleEntry(session).execute(
        date(2026, 4, 20),
        "Sell ETF",
        Decimal(10),
        "Broker",
        "Checking",
        CrossUnitLine("IE00B4L5Y983", Decimal(110), is_debit=False),
    )

    assert result.is_ok


def test_cross_unit_entry_balances_by_value_at_quantity_times_price(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    AddAccount(session).execute("Broker", AccountType.asset)
    AddUnit(session).execute("IE00B4L5Y983", "Core MSCI World", UnitKind.security)

    entry = RecordSimpleEntry(session).execute(
        date(2026, 3, 6),
        "Buy ETF",
        Decimal(10),
        "Checking",
        "Broker",
        CrossUnitLine("IE00B4L5Y983", Decimal(100), is_debit=True),
    ).unwrap()

    debits = sum((line.value for line in entry.lines if line.is_debit), Decimal(0))
    credits = sum((line.value for line in entry.lines if not line.is_debit), Decimal(0))
    assert debits == credits == Decimal(1000)


def test_base_currency_named_as_cross_unit_on_debit_side_is_rejected(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    AddAccount(session).execute("Broker", AccountType.asset)

    result = RecordSimpleEntry(session).execute(
        date(2026, 3, 6),
        "Buy ETF",
        Decimal(10),
        "Checking",
        "Broker",
        CrossUnitLine(BASE_CURRENCY, Decimal("1.1"), is_debit=True),
    )

    assert result.is_err
    assert isinstance(result.unwrap_err(), BaseCurrencyAsCrossUnit)


def test_base_currency_named_as_cross_unit_on_credit_side_is_rejected(session: Session) -> None:
    AddAccount(session).execute("Broker", AccountType.asset)
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")

    result = RecordSimpleEntry(session).execute(
        date(2026, 4, 20),
        "Sell ETF",
        Decimal(10),
        "Broker",
        "Checking",
        CrossUnitLine(BASE_CURRENCY, Decimal(1), is_debit=False),
    )

    assert result.is_err
    assert isinstance(result.unwrap_err(), BaseCurrencyAsCrossUnit)


def test_unknown_cross_unit_is_an_error_and_not_auto_created(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    AddAccount(session).execute("Broker", AccountType.asset)

    result = RecordSimpleEntry(session).execute(
        date(2026, 3, 6),
        "Buy ETF",
        Decimal(10),
        "Checking",
        "Broker",
        CrossUnitLine("IE00B4L5Y983", Decimal(100), is_debit=True),
    )

    assert result.is_err
    assert isinstance(result.unwrap_err(), UnitNotFoundError)
    units = ListUnits(session).execute().unwrap()
    assert "IE00B4L5Y983" not in [u.identifier for u in units]
