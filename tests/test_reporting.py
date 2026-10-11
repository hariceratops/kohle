"""Layer 2 — use case against `session`, pinned `TODAY`.

`value_balances`, `ValuedNetWorth`, `QueryValuedBalance` in kohle/use_cases/reporting.py (issues 035, 036, 038). Design §4, §11. Closes are seeded with `session.add(Price(...))`, as test_latest_close does.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from kohle.domain.domain_errors import AccountNotFoundError
from kohle.domain.models import AccountType, Price, UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.account_services import (
    add_account_service,
    get_account_by_name_service,
)
from kohle.services.journal_services import LineSpec, add_journal_entry_service
from kohle.services.unit_services import add_unit_service
from kohle.use_cases.journal import NetWorth, account_balance
from kohle.use_cases.prices import Fresh, NoClose, Stale
from kohle.use_cases.reporting import (
    QueryValuedBalance,
    ValuedNetWorth,
    summarise,
    value_balances,
)

TODAY = date(2026, 3, 10)
EUR = Decimal(1)


def _seed_close(session: Session, unit_id: int, age_days: int, price: str) -> None:
    session.add(Price(unit_id=unit_id, price_date=TODAY - timedelta(days=age_days), price=Decimal(price), source="file"))
    session.commit()


def _buy(ctx: DbTransactionContext, ref: str, account, unit, quantity: str, price: str, checking, eur) -> None:
    cost = Decimal(quantity) * Decimal(price)
    add_journal_entry_service(
        ctx, date(2026, 3, 2), ref, ref,
        [
            LineSpec(account.id, unit.id, Decimal(quantity), Decimal(price), is_debit=True),
            LineSpec(checking.id, eur.id, cost, EUR, is_debit=False),
        ],
    ).unwrap()


@pytest.fixture
def ledger(session: Session, people_root) -> dict:
    ctx = DbTransactionContext(session)
    checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap()
    depot_a = add_account_service(ctx, "Depot A", AccountType.asset, "DE2").unwrap()
    depot_b = add_account_service(ctx, "Depot B", AccountType.asset, "DE3").unwrap()
    salary = add_account_service(ctx, "Salary", AccountType.income).unwrap()
    alice = add_account_service(ctx, "Alice", AccountType.asset, None, people_root.id).unwrap()
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap()
    fresh = add_unit_service(ctx, "FRESH", "Fresh", UnitKind.security).unwrap()
    stale = add_unit_service(ctx, "STALE", "Stale", UnitKind.security).unwrap()
    never = add_unit_service(ctx, "NEVER", "Never fetched", UnitKind.security).unwrap()
    sold = add_unit_service(ctx, "SOLD", "Sold out", UnitKind.security).unwrap()

    add_journal_entry_service(
        ctx, date(2026, 3, 1), "salary", "Salary",
        [
            LineSpec(checking.id, eur.id, Decimal(10000), EUR, is_debit=True),
            LineSpec(salary.id, eur.id, Decimal(10000), EUR, is_debit=False),
        ],
    ).unwrap()
    _buy(ctx, "fresh-a", depot_a, fresh, "2", "10", checking, eur)
    _buy(ctx, "fresh-b", depot_b, fresh, "2", "10", checking, eur)
    _buy(ctx, "stale", depot_a, stale, "3", "50", checking, eur)
    _buy(ctx, "never", depot_a, never, "5", "4", checking, eur)
    _buy(ctx, "sold-in", depot_a, sold, "1", "7", checking, eur)
    add_journal_entry_service(
        ctx, date(2026, 3, 3), "sold-out", "sell",
        [
            LineSpec(checking.id, eur.id, Decimal(9), EUR, is_debit=True),
            LineSpec(depot_a.id, sold.id, Decimal(1), Decimal(9), is_debit=False),
        ],
    ).unwrap()
    add_journal_entry_service(
        ctx, date(2026, 3, 4), "alice", "Dinner for Alice",
        [
            LineSpec(alice.id, eur.id, Decimal(16), EUR, is_debit=True),
            LineSpec(checking.id, eur.id, Decimal(16), EUR, is_debit=False),
        ],
    ).unwrap()
    session.commit()
    _seed_close(session, fresh.id, 1, "12")
    _seed_close(session, stale.id, 30, "60")
    _seed_close(session, sold.id, 1, "99")
    return {"depot_a": depot_a, "fresh": fresh, "stale": stale, "never": never, "sold": sold, "eur": eur}


def test_value_balances_looks_up_only_nonzero_non_base_rows(session: Session, ledger: dict) -> None:
    ctx = DbTransactionContext(session)
    balances = account_balance(ctx, ledger["depot_a"].id).unwrap()
    valued = value_balances(ctx, balances, TODAY, 7).unwrap()

    assert [v.balance for v in valued] == balances
    by_unit = {v.balance.unit_identifier: v.close for v in valued}
    assert isinstance(by_unit["FRESH"], Fresh)
    assert isinstance(by_unit["STALE"], Stale)
    assert by_unit["NEVER"] == NoClose()
    # SOLD has a stored close, yet its quantity is 0, so none is looked up.
    assert by_unit["SOLD"] is None


def test_value_balances_values_a_commodity_and_an_unbound_security_at_cost(session: Session) -> None:
    ctx = DbTransactionContext(session)
    checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap()
    box = add_account_service(ctx, "Box", AccountType.asset).unwrap()
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap()
    gold = add_unit_service(ctx, "XAU-G", "Gold", UnitKind.commodity).unwrap()
    _buy(ctx, "gold", box, gold, "2", "55", checking, eur)
    session.commit()

    balances = account_balance(ctx, box.id).unwrap()
    valued = value_balances(ctx, balances, TODAY, 7).unwrap()
    assert [v.close for v in valued] == [NoClose()]
    assert valued[0].market_value == Decimal(110)


def test_value_balances_gives_a_euro_row_no_close(session: Session, ledger: dict) -> None:
    ctx = DbTransactionContext(session)
    account = get_account_by_name_service(ctx, "Checking").unwrap()
    balances = account_balance(ctx, account.id).unwrap()
    valued = value_balances(ctx, balances, TODAY, 7).unwrap()
    assert [v.close for v in valued] == [None]
    assert valued[0].balance.unit_identifier == "EUR"


@pytest.mark.parametrize(("max_age", "fresh_age"), [(7, 7), (3, 3)])
def test_staleness_boundary_at_the_use_case_level(
    session: Session, ledger: dict, max_age: int, fresh_age: int
) -> None:
    ctx = DbTransactionContext(session)
    unit_id = ledger["never"].id
    _seed_close(session, unit_id, fresh_age, "5")
    balances = [b for b in account_balance(ctx, ledger["depot_a"].id).unwrap() if b.unit_identifier == "NEVER"]

    at_boundary = value_balances(ctx, balances, TODAY, max_age).unwrap()[0].close
    assert isinstance(at_boundary, Fresh)
    a_day_later = value_balances(ctx, balances, TODAY + timedelta(days=1), max_age).unwrap()[0].close
    assert isinstance(a_day_later, Stale)


def test_valued_net_worth_on_a_mixed_ledger(session: Session, ledger: dict) -> None:
    report = ValuedNetWorth(session).execute(TODAY, 7).unwrap()

    own = {r.balance.unit_identifier: r for r in report.own}
    # FRESH is held in two depots and is one row: (2 + 2) x 12.
    assert own["FRESH"].balance.quantity == Decimal(4)
    assert own["FRESH"].market_value == Decimal(48)
    assert isinstance(own["FRESH"].close, Fresh)
    assert own["STALE"].market_value == Decimal(180)
    assert isinstance(own["STALE"].close, Stale)
    assert own["NEVER"].market_value == Decimal(20)
    assert own["NEVER"].close == NoClose()
    assert own["SOLD"].market_value == Decimal(0)
    assert own["SOLD"].close is None
    assert own["EUR"].market_value == Decimal(9776)
    assert [r.market_value for r in report.receivables] == [Decimal(16)]

    expected = sum((r.market_value for r in report.own + report.receivables), Decimal(0))
    assert report.net_worth_at_market == expected == Decimal(10040)

    plain = NetWorth(session).execute().unwrap()
    assert report.at_cost.own_at_cost == plain.own_at_cost == Decimal(9986)
    assert report.at_cost.receivables_at_cost == plain.receivables_at_cost == Decimal(16)
    assert report.at_cost.net_worth_at_cost == plain.net_worth_at_cost


def test_net_worth_estimates(session: Session, ledger: dict) -> None:
    summary = ValuedNetWorth(session).execute(TODAY, 7).unwrap().estimates

    # Non-base nonzero rows: FRESH, STALE, NEVER. SOLD is zero; both EUR rows are base.
    assert (summary.holdings, summary.stale, summary.no_price, summary.estimated) == (3, 1, 1, 2)


def test_query_valued_balance_applies_the_rule_across_a_subtree(session: Session) -> None:
    ctx = DbTransactionContext(session)
    checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap()
    brokerage = add_account_service(ctx, "Brokerage", AccountType.asset).unwrap()
    depot_a = add_account_service(ctx, "Depot A", AccountType.asset, "DE2", brokerage.id).unwrap()
    depot_b = add_account_service(ctx, "Depot B", AccountType.asset, "DE3", brokerage.id).unwrap()
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap()
    fresh = add_unit_service(ctx, "FRESH", "Fresh", UnitKind.security).unwrap()
    never = add_unit_service(ctx, "NEVER", "Never fetched", UnitKind.security).unwrap()
    add_journal_entry_service(
        ctx, date(2026, 3, 1), "salary", "Salary",
        [
            LineSpec(checking.id, eur.id, Decimal(1000), EUR, is_debit=True),
            LineSpec(add_account_service(ctx, "Salary", AccountType.income).unwrap().id, eur.id, Decimal(1000), EUR, is_debit=False),
        ],
    ).unwrap()
    _buy(ctx, "fresh-a", depot_a, fresh, "2", "10", checking, eur)
    _buy(ctx, "fresh-b", depot_b, fresh, "3", "10", checking, eur)
    _buy(ctx, "never", depot_b, never, "5", "4", checking, eur)
    session.commit()
    _seed_close(session, fresh.id, 1, "12")

    valued = QueryValuedBalance(session).execute("Brokerage", TODAY, 7).unwrap()

    by_unit = {v.balance.unit_identifier: v for v in valued}
    assert isinstance(by_unit["FRESH"].close, Fresh)
    assert by_unit["FRESH"].market_value == Decimal(60)  # 5 shares across both depots at 12
    assert by_unit["NEVER"].close == NoClose()
    assert by_unit["NEVER"].market_value == Decimal(20)
    assert summarise(valued).holdings == 2


def test_query_valued_balance_of_an_unknown_account_is_an_error(session: Session) -> None:
    res = QueryValuedBalance(session).execute("Nowhere", TODAY, 7)

    assert res.is_err
    assert isinstance(res.unwrap_err(), AccountNotFoundError)
