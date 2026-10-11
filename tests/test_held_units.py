"""Layer 2 — use case against `session`.

`held_units` in journal.py (issue 030), design §6.2.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from kohle.domain.models import Account, AccountType, Unit, UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.account_services import add_account_service
from kohle.services.journal_services import LineSpec, add_journal_entry_service
from kohle.services.unit_services import add_unit_service
from kohle.use_cases.journal import held_units


def _trade(
    ctx: DbTransactionContext, day: date, reference: str, account: Account, cash: Account,
    security: Unit, eur: Unit, quantity: str, *, buy: bool,
) -> None:
    amount = Decimal(quantity)
    add_journal_entry_service(
        ctx, day, reference, reference,
        [
            LineSpec(account.id, security.id, amount, Decimal(10), is_debit=buy),
            LineSpec(cash.id, eur.id, amount * 10, Decimal(1), is_debit=not buy),
        ],
    ).unwrap()


def _identifiers(ctx: DbTransactionContext) -> list[str]:
    return [unit.identifier for unit in held_units(ctx).unwrap()]


def test_fully_sold_fractional_position_is_not_held(session: Session) -> None:
    ctx = DbTransactionContext(session)
    depot = add_account_service(ctx, "Depot", AccountType.asset).unwrap()
    cash = add_account_service(ctx, "Cash", AccountType.asset).unwrap()
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap()
    etf = add_unit_service(ctx, "ETF", "Savings plan", UnitKind.security).unwrap()
    # SQLite stores these as REAL, so a SQL SUM would leave 2.78e-17 behind.
    _trade(ctx, date(2026, 1, 1), "b1", depot, cash, etf, eur, "0.1", buy=True)
    _trade(ctx, date(2026, 1, 2), "b2", depot, cash, etf, eur, "0.2", buy=True)
    _trade(ctx, date(2026, 1, 3), "s1", depot, cash, etf, eur, "0.3", buy=False)
    session.commit()

    assert "ETF" not in _identifiers(ctx)


def test_transfer_between_two_depots_stays_held(session: Session) -> None:
    ctx = DbTransactionContext(session)
    depot_a = add_account_service(ctx, "DepotA", AccountType.asset).unwrap()
    depot_b = add_account_service(ctx, "DepotB", AccountType.asset).unwrap()
    cash = add_account_service(ctx, "Cash", AccountType.asset).unwrap()
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap()
    etf = add_unit_service(ctx, "ETF", "ETF", UnitKind.security).unwrap()
    _trade(ctx, date(2026, 1, 1), "b1", depot_a, cash, etf, eur, "5", buy=True)
    add_journal_entry_service(
        ctx, date(2026, 1, 2), "move", "move",
        [
            LineSpec(depot_b.id, etf.id, Decimal(5), Decimal(10), is_debit=True),
            LineSpec(depot_a.id, etf.id, Decimal(5), Decimal(10), is_debit=False),
        ],
    ).unwrap()
    session.commit()

    assert "ETF" in _identifiers(ctx)


def test_held_units_is_kind_agnostic(session: Session) -> None:
    ctx = DbTransactionContext(session)
    depot = add_account_service(ctx, "Depot", AccountType.asset).unwrap()
    cash = add_account_service(ctx, "Cash", AccountType.asset).unwrap()
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap()
    etf = add_unit_service(ctx, "ETF", "ETF", UnitKind.security).unwrap()
    _trade(ctx, date(2026, 1, 1), "b1", depot, cash, etf, eur, "5", buy=True)
    session.commit()

    assert _identifiers(ctx) == ["ETF", "EUR"]
