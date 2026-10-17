"""Layer 2 — use case against `session`, pinned dates.

`NetWorthHistory` in kohle/use_cases/reporting.py (issue 045). Design §5, §15.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from kohle.domain.models import AccountType, Price, UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.account_services import add_account_service
from kohle.services.journal_services import LineSpec, add_journal_entry_service
from kohle.services.unit_services import add_unit_service
from kohle.use_cases.prices import NoClose
from kohle.use_cases.reporting import HistoryRow, NetWorthHistory, ValuedNetWorth
from kohle.use_cases.sampling import PeriodEnd

EUR = Decimal(1)
TODAY = date(2026, 3, 10)


def _close(session: Session, unit_id: int, on: date, price: str) -> None:
    session.add(Price(unit_id=unit_id, price_date=on, price=Decimal(price), source="file"))
    session.commit()


@pytest.fixture
def ledger(session: Session, people_root) -> dict:
    ctx = DbTransactionContext(session)
    checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap()
    depot = add_account_service(ctx, "Depot", AccountType.asset, "DE2").unwrap()
    salary = add_account_service(ctx, "Salary", AccountType.income).unwrap()
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap()
    sec = add_unit_service(ctx, "X1", "Thing", UnitKind.security).unwrap()

    def entry(on: date, ref: str, lines: list[LineSpec]) -> None:
        add_journal_entry_service(ctx, on, ref, ref, lines).unwrap()

    entry(date(2026, 1, 10), "salary", [
        LineSpec(checking.id, eur.id, Decimal(1000), EUR, is_debit=True),
        LineSpec(salary.id, eur.id, Decimal(1000), EUR, is_debit=False),
    ])
    # Dated on a sample date (the 15th): included at 2026-02-15.
    entry(date(2026, 2, 15), "buy-1", [
        LineSpec(depot.id, sec.id, Decimal(2), Decimal(10), is_debit=True),
        LineSpec(checking.id, eur.id, Decimal(20), EUR, is_debit=False),
    ])
    # The next day: excluded at 2026-02-15.
    entry(date(2026, 2, 16), "buy-2", [
        LineSpec(depot.id, sec.id, Decimal(1), Decimal(10), is_debit=True),
        LineSpec(checking.id, eur.id, Decimal(10), EUR, is_debit=False),
    ])
    session.commit()
    _close(session, sec.id, date(2026, 2, 10), "12")
    _close(session, sec.id, date(2026, 3, 5), "20")
    return {"sec": sec}


def _by_date(rows: list[HistoryRow]) -> dict[date, HistoryRow]:
    return {r.on: r for r in rows}


def test_a_line_on_a_sample_date_is_included_and_the_next_days_is_excluded(session: Session, ledger: dict) -> None:
    rows = _by_date(NetWorthHistory(session).execute(date(2026, 2, 1), date(2026, 2, 28), 7).unwrap())

    # 2 X1 bought on the 15th: 1000 - 20 cash plus 2 * 12 at the 02-10 close.
    assert rows[date(2026, 2, 15)].report.at_cost.net_worth_at_cost == Decimal(1000)
    assert rows[date(2026, 2, 15)].report.net_worth_at_market == Decimal(980 + 24)
    # The 16th's purchase of 1 X1 is in by month-end.
    assert rows[date(2026, 2, 28)].report.at_cost.net_worth_at_cost == Decimal(1000)
    assert rows[date(2026, 2, 28)].report.net_worth_at_market == Decimal(970 + 36)


def test_a_close_is_never_a_later_one_and_is_marked_stale_relative_to_the_sample_date(
    session: Session, ledger: dict
) -> None:
    rows = _by_date(NetWorthHistory(session).execute(date(2026, 2, 1), date(2026, 3, 10), 7).unwrap())

    # 02-28 is 18 days after the 02-10 close (stale), and the 03-05 close is later.
    feb_end = rows[date(2026, 2, 28)].report
    assert feb_end.net_worth_at_market == Decimal(970 + 3 * 12)
    assert (feb_end.estimates.estimated, feb_end.estimates.holdings) == (1, 1)
    # 02-15 is 5 days after the close: fresh.
    assert rows[date(2026, 2, 15)].report.estimates.estimated == 0
    # 03-10 reads the 03-05 close.
    assert rows[date(2026, 3, 10)].report.net_worth_at_market == Decimal(970 + 3 * 20)


def test_a_date_before_any_close_is_valued_at_cost_and_marked(session: Session, people_root) -> None:
    ctx = DbTransactionContext(session)
    checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap()
    depot = add_account_service(ctx, "Depot", AccountType.asset, "DE2").unwrap()
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap()
    sec = add_unit_service(ctx, "X1", "Thing", UnitKind.security).unwrap()
    add_journal_entry_service(ctx, date(2026, 1, 2), "buy", "buy", [
        LineSpec(depot.id, sec.id, Decimal(2), Decimal(10), is_debit=True),
        LineSpec(checking.id, eur.id, Decimal(20), EUR, is_debit=False),
    ]).unwrap()
    session.commit()
    _close(session, sec.id, date(2026, 2, 1), "50")

    jan = _by_date(NetWorthHistory(session).execute(None, date(2026, 1, 31), 7).unwrap())[date(2026, 1, 15)]

    assert [v.close for v in jan.report.own if v.balance.unit_identifier == "X1"] == [NoClose()]
    assert jan.report.net_worth_at_market == jan.report.at_cost.net_worth_at_cost == Decimal(0)
    assert (jan.report.estimates.estimated, jan.report.estimates.holdings) == (1, 1)


def test_the_default_start_is_the_earliest_entry(session: Session, ledger: dict) -> None:
    rows = NetWorthHistory(session).execute(None, date(2026, 2, 28), 7).unwrap()

    assert [r.on for r in rows] == [date(2026, 1, 15), date(2026, 1, 31), date(2026, 2, 15), date(2026, 2, 28)]


def test_a_past_to_ends_with_a_row_dated_to(session: Session, ledger: dict) -> None:
    rows = NetWorthHistory(session).execute(date(2026, 2, 1), date(2026, 2, 20), 7).unwrap()

    assert rows[-1].on == date(2026, 2, 20)
    assert rows[-1].report.net_worth_at_market == Decimal(970 + 3 * 12)


def test_an_empty_ledger_gives_one_row_dated_to(session: Session, people_root) -> None:
    rows = NetWorthHistory(session).execute(None, TODAY, 7).unwrap()

    assert [r.on for r in rows] == [TODAY]
    assert rows[0].report.net_worth_at_market == 0


def test_the_last_row_at_today_equals_valued_net_worth(session: Session, ledger: dict) -> None:
    last = NetWorthHistory(session).execute(None, TODAY, 7).unwrap()[-1]
    now = ValuedNetWorth(session).execute(TODAY, 7).unwrap()

    assert last.on == TODAY
    assert last.report.at_cost.net_worth_at_cost == now.at_cost.net_worth_at_cost
    assert last.report.net_worth_at_market == now.net_worth_at_market
    assert last.report.estimates == now.estimates


def test_the_salary_day_row_is_dated_the_working_day_and_includes_that_days_lines(
    session: Session, ledger: dict
) -> None:
    ctx = DbTransactionContext(session)
    checking = add_account_service(ctx, "Checking2", AccountType.asset, "DE3").unwrap()
    salary = add_account_service(ctx, "Salary2", AccountType.income).unwrap()
    eur = add_unit_service(ctx, "EUR2", "Euro", UnitKind.currency).unwrap()
    add_journal_entry_service(ctx, date(2026, 2, 27), "pay", "pay", [
        LineSpec(checking.id, eur.id, Decimal(500), EUR, is_debit=True),
        LineSpec(salary.id, eur.id, Decimal(500), EUR, is_debit=False),
    ]).unwrap()
    session.commit()

    rows = NetWorthHistory(session).execute(
        date(2026, 2, 1), date(2026, 2, 28), 7, PeriodEnd.last_working_day, "BY"
    ).unwrap()
    by_date = _by_date(rows)

    assert [r.on for r in rows] == [date(2026, 2, 15), date(2026, 2, 27), date(2026, 2, 28)]
    assert by_date[date(2026, 2, 27)].report.at_cost.net_worth_at_cost == Decimal(1500)
