"""Layer 3 scenario for importer-plugins-for-assets (issue 028): design section 7.3 end to end."""

from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kohle.app.plugins.kohle_simple_broker_importer import (
    SimpleBrokerStatementImporter,
)
from kohle.domain.models import (
    AccountType,
    Classification,
    JournalEntry,
    OperationGroup,
    UnitKind,
)
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.journal import ImportStatement, QueryAccountBalance
from kohle.use_cases.rules import AddRule
from kohle.use_cases.units import AddUnit

FIXTURE = Path(__file__).parent / "fixtures" / "simple_broker.csv"


def _import(session: Session, cash: str, instrument: str) -> int:
    rows = SimpleBrokerStatementImporter().import_statement(str(FIXTURE)).unwrap()
    return ImportStatement(session).execute(cash, rows, instrument).unwrap()


def _dividend_lines(session: Session, cash_name: str) -> set[tuple[str, Decimal, bool]]:
    entry = session.scalars(select(JournalEntry).where(JournalEntry.reference.like("%:D-2001"))).all()
    (entry,) = [e for e in entry if any(line.account.name == cash_name for line in e.lines)]
    return {(line.account.name, line.quantity, line.is_debit) for line in entry.lines}


def test_broker_statement_scenario(session: Session) -> None:
    for name in ("Broker Cash", "Depot", "Broker Cash 2", "Depot 2", "Dividends"):
        account_type = AccountType.income if name == "Dividends" else AccountType.asset
        AddAccount(session).execute(name, account_type).unwrap()
    AddUnit(session).execute("DE0005190003", "BMW", UnitKind.security).unwrap()

    assert _import(session, "Broker Cash", "Depot") == 3

    (position,) = QueryAccountBalance(session).execute("Depot").unwrap()
    assert (position.unit_identifier, position.quantity, position.average_cost) == (
        "DE0005190003",
        Decimal(6),
        Decimal("95.50"),
    )

    # A dividend is money in: a debit on the asset account, not a credit.
    assert _dividend_lines(session, "Broker Cash") == {
        ("Broker Cash", Decimal("12.40"), True),
        ("Unclassified Income", Decimal("12.40"), False),
    }
    assert session.scalar(select(func.count()).select_from(Classification)) == 1

    groups = session.scalar(select(func.count()).select_from(OperationGroup))
    assert _import(session, "Broker Cash", "Depot") == 0
    assert session.scalar(select(func.count()).select_from(OperationGroup)) == groups

    AddRule(session).execute("^Dividend", "Dividends").unwrap()
    assert _import(session, "Broker Cash 2", "Depot 2") == 3
    assert _dividend_lines(session, "Broker Cash 2") == {
        ("Broker Cash 2", Decimal("12.40"), True),
        ("Dividends", Decimal("12.40"), False),
    }
