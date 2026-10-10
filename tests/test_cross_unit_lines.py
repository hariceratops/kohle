"""_cross_unit_lines helper (issue 027)."""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from kohle.domain.models import AccountType, UnitKind
from kohle.services.journal_services import LineSpec
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.journal import CrossUnitLine, RecordSimpleEntry, _cross_unit_lines
from kohle.use_cases.units import AddUnit


def _lines(into_holding: bool) -> list[LineSpec]:
    return _cross_unit_lines(
        holding_account_id=1,
        holding_unit_id=2,
        quantity=Decimal(10),
        unit_price=Decimal("95.50"),
        cash_account_id=3,
        cash_unit_id=4,
        into_holding=into_holding,
    )


def test_buy_debits_holding_and_credits_cash() -> None:
    assert _lines(True) == [
        LineSpec(1, 2, Decimal(10), Decimal("95.50"), is_debit=True),
        LineSpec(3, 4, Decimal("955.00"), Decimal(1), is_debit=False),
    ]


def test_sell_credits_holding_and_debits_cash() -> None:
    assert _lines(False) == [
        LineSpec(1, 2, Decimal(10), Decimal("95.50"), is_debit=False),
        LineSpec(3, 4, Decimal("955.00"), Decimal(1), is_debit=True),
    ]


def test_record_simple_entry_still_produces_its_old_lines(session: Session) -> None:
    cash = AddAccount(session).execute("Cash", AccountType.asset).unwrap()
    depot = AddAccount(session).execute("Depot", AccountType.asset).unwrap()
    eur = AddUnit(session).execute("EUR", "Euro", UnitKind.currency).unwrap()
    share = AddUnit(session).execute("ISIN1", "Share", UnitKind.security).unwrap()

    entry = RecordSimpleEntry(session).execute(
        date(2026, 3, 1), "Buy", Decimal(10), "Cash", "Depot", CrossUnitLine("ISIN1", Decimal("95.50"), True)
    ).unwrap()

    observed = {
        (line.account_id, line.unit_id, line.quantity, line.unit_price, line.is_debit)
        for line in entry.lines
    }
    assert observed == {
        (depot.id, share.id, Decimal(10), Decimal("95.50"), True),
        (cash.id, eur.id, Decimal("955.00"), Decimal(1), False),
    }
