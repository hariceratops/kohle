"""ImportStatement security branch (issue 027)."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kohle.domain.domain_errors import (
    AccountNotFoundError,
    MalformedStatementRow,
    MissingInstrumentAccount,
    NotASecurityUnit,
    PostingToNonLeafAccount,
    UnknownInstruments,
)
from kohle.domain.models import (
    Account,
    AccountType,
    Classification,
    JournalEntry,
    JournalLine,
    Operation,
    OperationGroup,
    Unit,
    UnitKind,
)
from kohle.plugin.importer_plugin import CashRow, SecurityRow, StatementRow
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.journal import ImportStatement
from kohle.use_cases.units import AddUnit

_TABLES = (JournalEntry, JournalLine, Classification, Unit, Account, OperationGroup, Operation)

_BUY = SecurityRow(
    entry_date=date(2026, 3, 2),
    reference="T-1",
    description="Buy X1",
    instrument_identifier="X1",
    quantity=Decimal(10),
    unit_price=Decimal("95.50"),
)
_SELL = replace(_BUY, reference="T-2", description="Sell X1", quantity=Decimal(-4), unit_price=Decimal("101.25"))
_DIVIDEND = CashRow(
    entry_date=date(2026, 4, 15),
    reference="D-1",
    description="Dividend X1",
    amount=Decimal("12.40"),
    counterparty_name=None,
    counterparty_iban=None,
)


def _snapshot(session: Session) -> list[tuple[int, int | None]]:
    return [
        (session.scalar(select(func.count()).select_from(t)), session.scalar(select(func.max(t.id))))
        for t in _TABLES
    ]


def _count(session: Session, table: type) -> int:
    return session.scalar(select(func.count()).select_from(table))


@pytest.fixture
def ledger(session: Session) -> Session:
    for name in ("Broker Cash", "Depot", "Other Depot"):
        AddAccount(session).execute(name, AccountType.asset).unwrap()
    AddUnit(session).execute("X1", "X", UnitKind.security).unwrap()
    return session


def _entry(session: Session, reference: str) -> JournalEntry:
    return session.scalars(select(JournalEntry).where(JournalEntry.reference.like(f"%:{reference}"))).one()


def _lines(entry: JournalEntry) -> set[tuple[str, str, Decimal, Decimal, bool]]:
    return {
        (line.account.name, line.unit.identifier, line.quantity, line.unit_price, line.is_debit)
        for line in entry.lines
    }


def test_buy_and_sell_post_balanced_transfers(ledger: Session) -> None:
    imported = ImportStatement(ledger).execute("Broker Cash", [_BUY, _SELL, _DIVIDEND], "Depot").unwrap()

    assert imported == 3
    assert _lines(_entry(ledger, "T-1")) == {
        ("Depot", "X1", Decimal(10), Decimal("95.50"), True),
        ("Broker Cash", "EUR", Decimal("955.00"), Decimal(1), False),
    }
    assert _lines(_entry(ledger, "T-2")) == {
        ("Depot", "X1", Decimal(4), Decimal("101.25"), False),
        ("Broker Cash", "EUR", Decimal("405.00"), Decimal(1), True),
    }


def test_security_rows_record_no_classification(ledger: Session) -> None:
    ImportStatement(ledger).execute("Broker Cash", [_BUY, _SELL, _DIVIDEND], "Depot").unwrap()

    assert _count(ledger, Classification) == 1
    trade = _entry(ledger, "T-1")
    assert (trade.counterparty_name, trade.counterparty_iban) == (None, None)


def test_unknown_instruments_are_all_named_in_one_error(ledger: Session) -> None:
    rows: list[StatementRow] = [
        replace(_BUY, reference="a", instrument_identifier="ZZ2"),
        replace(_BUY, reference="b", instrument_identifier="AA1"),
        replace(_BUY, reference="c", instrument_identifier="ZZ2"),
        _DIVIDEND,
    ]
    before = _snapshot(ledger)

    error = ImportStatement(ledger).execute("Broker Cash", rows, "Depot").unwrap_err()

    assert isinstance(error, UnknownInstruments)
    assert error.identifiers == ["AA1", "ZZ2"]
    assert "add-unit AA1" in str(error)
    assert _snapshot(ledger) == before


def test_a_currency_unit_is_not_a_security(ledger: Session) -> None:
    AddUnit(ledger).execute("EUR", "Euro", UnitKind.currency).unwrap()
    before = _snapshot(ledger)

    error = ImportStatement(ledger).execute(
        "Broker Cash", [replace(_BUY, instrument_identifier="EUR")], "Depot"
    ).unwrap_err()

    assert isinstance(error, NotASecurityUnit)
    assert error.identifier == "EUR"
    assert _snapshot(ledger) == before


def test_trades_without_an_instrument_account_are_refused(ledger: Session) -> None:
    before = _snapshot(ledger)

    error = ImportStatement(ledger).execute("Broker Cash", [_DIVIDEND, _BUY]).unwrap_err()

    assert isinstance(error, MissingInstrumentAccount)
    assert _snapshot(ledger) == before


def test_missing_instrument_account_is_refused_even_on_reimport(ledger: Session) -> None:
    ImportStatement(ledger).execute("Broker Cash", [_BUY], "Depot").unwrap()

    error = ImportStatement(ledger).execute("Broker Cash", [_BUY]).unwrap_err()

    assert isinstance(error, MissingInstrumentAccount)


@pytest.mark.parametrize(("cash", "instrument"), [("Nope", "Depot"), ("Broker Cash", "Nope")])
def test_a_nonexistent_account_aborts_the_import(ledger: Session, cash: str, instrument: str) -> None:
    before = _snapshot(ledger)

    error = ImportStatement(ledger).execute(cash, [_BUY], instrument).unwrap_err()

    assert isinstance(error, AccountNotFoundError)
    assert _snapshot(ledger) == before


def test_a_named_instrument_account_must_exist_even_without_trades(ledger: Session) -> None:
    error = ImportStatement(ledger).execute("Broker Cash", [_DIVIDEND], "Nope").unwrap_err()

    assert isinstance(error, AccountNotFoundError)


def test_a_non_leaf_instrument_account_aborts_with_nothing_written(ledger: Session) -> None:
    AddAccount(ledger).execute("Sub", AccountType.asset, None, "Depot").unwrap()
    before = _snapshot(ledger)

    error = ImportStatement(ledger).execute("Broker Cash", [_DIVIDEND, _BUY], "Depot").unwrap_err()

    assert isinstance(error, PostingToNonLeafAccount)
    assert _snapshot(ledger) == before


def test_a_security_row_without_a_price_as_the_last_row_rejects_everything(ledger: Session) -> None:
    with pytest.raises(TypeError):
        SecurityRow(  # type: ignore[call-arg]
            entry_date=date(2026, 3, 2),
            reference="x",
            description="x",
            instrument_identifier="X1",
            quantity=Decimal(1),
        )
    priceless = replace(_BUY, reference="T-9", unit_price=None)  # type: ignore[arg-type]
    before = _snapshot(ledger)

    error = ImportStatement(ledger).execute("Broker Cash", [_BUY, _SELL, priceless], "Depot").unwrap_err()

    assert isinstance(error, MalformedStatementRow)
    assert (error.row_number, error.field) == (3, "unit_price")
    assert _snapshot(ledger) == before


def test_reimport_under_a_different_instrument_account_posts_nothing(ledger: Session) -> None:
    ImportStatement(ledger).execute("Broker Cash", [_BUY], "Depot").unwrap()
    before = _snapshot(ledger)

    assert ImportStatement(ledger).execute("Broker Cash", [_BUY], "Other Depot").unwrap() == 0

    assert _snapshot(ledger) == before


def test_trade_references_are_scoped_by_the_cash_account(ledger: Session) -> None:
    AddAccount(ledger).execute("Second Cash", AccountType.asset).unwrap()

    ImportStatement(ledger).execute("Broker Cash", [_BUY], "Depot").unwrap()
    assert ImportStatement(ledger).execute("Second Cash", [_BUY], "Depot").unwrap() == 1

    cash_id = ledger.scalars(select(Account.id).where(Account.name == "Broker Cash")).one()
    assert ledger.scalars(select(JournalEntry.reference)).first() == f"{cash_id}:T-1"
    assert _count(ledger, JournalEntry) == 2
