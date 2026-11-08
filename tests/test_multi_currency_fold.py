"""Layer 1 — the cost fold and entry balancing for currency lines (issues 111, 113). Design §2, §14."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from kohle.domain.domain_errors import (
    ConversionBetweenCurrencies,
    CurrencyLineNotAtPar,
    NonPositiveQuantity,
    UnbalancedEntry,
)
from kohle.domain.models import AccountType, JournalEntry, JournalLine, Unit, UnitKind
from kohle.services.journal_services import LineSpec
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.journal import RecordJournalEntry, aggregate_by_unit
from kohle.use_cases.lots import replay
from kohle.use_cases.units import AddUnit

INR = Unit(identifier="INR", kind=UnitKind.currency, id=7)
INFY = Unit(identifier="INFY", kind=UnitKind.security, id=8)
EUR = Unit(identifier="EUR", kind=UnitKind.currency, id=1)


def _line(
    line_id: int, entry_id: int, day: int, unit: Unit, quantity: str, *,
    is_debit: bool, price: str = "1", cost: str | None = None, priced_in_inr: bool = False,
) -> JournalLine:
    return JournalLine(
        id=line_id,
        entry=JournalEntry(id=entry_id, entry_date=date(2026, 1, day)),
        account_id=1,
        unit=unit,
        unit_id=unit.id,
        quantity=Decimal(quantity),
        unit_price=Decimal(price),
        cost=None if cost is None else Decimal(cost),
        price_unit_id=INR.id if priced_in_inr else None,
        is_debit=is_debit,
    )


def _remit_remit_buy() -> list[JournalLine]:
    return [
        _line(1, 1, 1, INR, "90000", is_debit=True, cost="1000"),
        _line(2, 2, 2, INR, "100000", is_debit=True, cost="1100"),
        _line(3, 3, 3, INR, "120000", is_debit=False, priced_in_inr=True),
        _line(4, 3, 3, INFY, "100", is_debit=True, price="1200", cost="120000", priced_in_inr=True),
    ]


def test_fold_is_fifo_for_a_currency() -> None:
    lines = _remit_remit_buy()
    costs = replay(lines, {1: "IndianBank"}).unwrap().costs

    balances = {b.unit_identifier: b for b in aggregate_by_unit(lines, costs)}

    assert balances["INR"].at_cost == Decimal(770)
    assert balances["INFY"].at_cost == Decimal(1330)
    total = sum((b.at_cost for b in balances.values()), Decimal(0))
    assert total == Decimal(2100)
    # A moving average would take 2,100 * 120,000 / 190,000 off the rupees and leave 773.68.
    moving_average = Decimal(2100) - Decimal(2100) * Decimal(120000) / Decimal(190000)
    assert round(moving_average, 2) == Decimal("773.68")
    assert total != round(moving_average + Decimal(1330), 2)


def test_fold_without_costs_is_unchanged() -> None:
    lines = [
        _line(1, 1, 1, INFY, "10", is_debit=True, price="100"),
        _line(2, 2, 2, INFY, "10", is_debit=True, price="120"),
        _line(3, 3, 3, INFY, "5", is_debit=False, price="130"),
    ]

    plain = aggregate_by_unit(lines)

    assert aggregate_by_unit(lines, {}) == plain
    (balance,) = plain
    assert (balance.quantity, balance.at_cost) == (Decimal(15), Decimal(1650))


def _record(session: Session, lines: list[LineSpec]):
    return RecordJournalEntry(session).execute(date(2026, 3, 1), "ref-1", "entry", lines)


@pytest.fixture
def ids(session: Session) -> dict[str, int]:
    out = {}
    for name, kind in (("EUR", UnitKind.currency), ("INR", UnitKind.currency), ("INFY", UnitKind.security)):
        out[name] = AddUnit(session).execute(name, name, kind).unwrap().id
    for name, account_type in (
        ("Girokonto", AccountType.asset), ("IndianBank", AccountType.asset),
        ("Demat", AccountType.asset), ("Groceries", AccountType.expense),
    ):
        out[name] = AddAccount(session).execute(name, account_type).unwrap().id
    return out


def test_validate_lines_balances_per_price_currency(session: Session, ids: dict[str, int]) -> None:
    inr = ids["INR"]

    # Balanced in rupees, with no euro figure on either line.
    ok = _record(session, [
        LineSpec(ids["IndianBank"], inr, Decimal(120000), Decimal(1), False, price_unit_id=inr),
        LineSpec(ids["Demat"], ids["INFY"], Decimal(100), Decimal(1200), True, cost=Decimal(120000), price_unit_id=inr),
    ])
    assert ok.is_ok

    # V1: out of balance in rupees, named as such.
    unbalanced = RecordJournalEntry(session).execute(date(2026, 3, 2), "ref-2", "entry", [
        LineSpec(ids["IndianBank"], inr, Decimal(100000), Decimal(1), False, price_unit_id=inr),
        LineSpec(ids["Demat"], ids["INFY"], Decimal(100), Decimal(1200), True, cost=Decimal(120000), price_unit_id=inr),
    ]).unwrap_err()
    assert isinstance(unbalanced, UnbalancedEntry)
    assert str(unbalanced) == "Entry does not balance in INR: debits 120000 against credits 100000"

    # V3: a line of the price currency is at par.
    not_at_par = RecordJournalEntry(session).execute(date(2026, 3, 3), "ref-3", "entry", [
        LineSpec(ids["IndianBank"], inr, Decimal(100), Decimal("0.5"), False, price_unit_id=inr),
        LineSpec(ids["Groceries"], inr, Decimal(50), Decimal(1), True, price_unit_id=inr),
    ]).unwrap_err()
    assert isinstance(not_at_par, CurrencyLineNotAtPar)

    # V4: no conversion between two non-base currencies, or into one from the base.
    conversion = RecordJournalEntry(session).execute(date(2026, 3, 4), "ref-4", "entry", [
        LineSpec(ids["Girokonto"], ids["EUR"], Decimal(100), Decimal(1), False, price_unit_id=inr),
        LineSpec(ids["IndianBank"], inr, Decimal(100), Decimal(1), True, price_unit_id=inr),
    ]).unwrap_err()
    assert isinstance(conversion, ConversionBetweenCurrencies)
    assert str(conversion).startswith("EUR cannot be priced in INR")

    # V6: a priced or totalled line has a quantity above 0.
    non_positive = RecordJournalEntry(session).execute(date(2026, 3, 5), "ref-5", "entry", [
        LineSpec(ids["IndianBank"], inr, Decimal(0), Decimal(1), False, price_unit_id=inr),
        LineSpec(ids["Groceries"], inr, Decimal(0), Decimal(1), True, price_unit_id=inr),
    ]).unwrap_err()
    assert isinstance(non_positive, NonPositiveQuantity)


def test_base_currency_imbalance_keeps_todays_message(session: Session, ids: dict[str, int]) -> None:
    error = RecordJournalEntry(session).execute(date(2026, 3, 1), "ref-1", "entry", [
        LineSpec(ids["Groceries"], ids["EUR"], Decimal(80), Decimal(1), True),
        LineSpec(ids["Girokonto"], ids["EUR"], Decimal(70), Decimal(1), False),
    ]).unwrap_err()

    assert isinstance(error, UnbalancedEntry)
    assert str(error) == "Entry does not balance: debits 80 against credits 70"
