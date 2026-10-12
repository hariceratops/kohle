"""Layer 3 — CLI through `CliRunner` with `session_factory`.

`net-worth` and `balance` market value, estimates and `--max-age-days` (issues 035-038). Design §6, §11.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from click.testing import CliRunner
from sqlalchemy.orm import sessionmaker

from kohle.app.cli.cli import cli
from kohle.domain.models import AccountType, Price, UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.account_services import add_account_service
from kohle.services.journal_services import LineSpec, add_journal_entry_service
from kohle.services.unit_services import add_unit_service
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.journal import PEOPLE_ROOT

EUR = Decimal(1)


@pytest.fixture
def mixed_ledger(session_factory: sessionmaker) -> None:
    """EUR cash, a fresh and a stale security, one never fetched, and a euro receivable.
    Closes are dated relative to the real today, well away from the 7-day threshold."""
    with session_factory() as session:
        ctx = DbTransactionContext(session)
        people = AddAccount(session).execute(PEOPLE_ROOT, AccountType.asset).unwrap()
        checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap()
        depot = add_account_service(ctx, "Depot", AccountType.asset, "DE2").unwrap()
        salary = add_account_service(ctx, "Salary", AccountType.income).unwrap()
        alice = add_account_service(ctx, "Alice", AccountType.asset, None, people.id).unwrap()
        eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap()
        units = {
            name: add_unit_service(ctx, name, name, UnitKind.security).unwrap()
            for name in ("FRESH", "STALE", "NEVER")
        }
        add_journal_entry_service(
            ctx, date(2026, 3, 1), "salary", "Salary",
            [
                LineSpec(checking.id, eur.id, Decimal(1000), EUR, is_debit=True),
                LineSpec(salary.id, eur.id, Decimal(1000), EUR, is_debit=False),
            ],
        ).unwrap()
        for name, quantity, price in (("FRESH", "10", "10"), ("STALE", "3", "50"), ("NEVER", "5", "4")):
            add_journal_entry_service(
                ctx, date(2026, 3, 2), f"buy-{name}", f"buy {name}",
                [
                    LineSpec(depot.id, units[name].id, Decimal(quantity), Decimal(price), is_debit=True),
                    LineSpec(checking.id, eur.id, Decimal(quantity) * Decimal(price), EUR, is_debit=False),
                ],
            ).unwrap()
        add_journal_entry_service(
            ctx, date(2026, 3, 3), "alice", "Dinner for Alice",
            [
                LineSpec(alice.id, eur.id, Decimal(16), EUR, is_debit=True),
                LineSpec(checking.id, eur.id, Decimal(16), EUR, is_debit=False),
            ],
        ).unwrap()
        today = date.today()  # noqa: DTZ011 - matches the CLI's own clock
        session.add(Price(unit_id=units["FRESH"].id, price_date=today - timedelta(days=1), price=Decimal(12), source="file"))
        session.add(Price(unit_id=units["STALE"].id, price_date=today - timedelta(days=30), price=Decimal(60), source="file"))
        session.commit()


def test_net_worth_columns_and_lines(session_factory: sessionmaker, mixed_ledger: None) -> None:
    result = CliRunner().invoke(cli, ["net-worth"], obj=session_factory)
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()

    assert lines[0].split() == ["section", "unit", "quantity", "price", "price", "date", "market", "value", "status", "at", "cost"]

    stale_date = (date.today() - timedelta(days=30)).isoformat()  # noqa: DTZ011
    fresh_row = next(r for r in lines if " FRESH " in r)
    assert "120.00" in fresh_row and "fresh" in fresh_row and fresh_row.split()[-1] == "100.00"
    stale_row = next(r for r in lines if " STALE " in r)
    assert f"stale ({stale_date})" in stale_row and "180.00" in stale_row and stale_row.split()[-1] == "150.00"
    never_row = next(r for r in lines if " NEVER " in r)
    assert "no price (at cost)" in never_row and "20.00" in never_row and never_row.split()[-1] == "20.00"
    eur_row = next(r for r in lines if r.startswith("Own accounts") and " EUR " in r)
    assert eur_row.split()[-3:] == ["714.00", "-", "714.00"]
    assert eur_row.split()[4:6] == ["-", "-"]

    # at cost: 714 + 100 + 150 + 20 + 16 = 1000; at market swaps 120/180 for 100/150.
    assert "Net worth (at cost): 1000.00" in lines
    assert "Net worth (at market): 1050.00" in lines


def test_net_worth_summary_on_a_euro_only_ledger(session_factory: sessionmaker) -> None:
    with session_factory() as session:
        ctx = DbTransactionContext(session)
        AddAccount(session).execute(PEOPLE_ROOT, AccountType.asset).unwrap()
        checking = add_account_service(ctx, "Checking", AccountType.asset, "DE1").unwrap()
        salary = add_account_service(ctx, "Salary", AccountType.income).unwrap()
        eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap()
        add_journal_entry_service(
            ctx, date(2026, 3, 1), "salary", "Salary",
            [
                LineSpec(checking.id, eur.id, Decimal(1000), EUR, is_debit=True),
                LineSpec(salary.id, eur.id, Decimal(1000), EUR, is_debit=False),
            ],
        ).unwrap()
        session.commit()

    result = CliRunner().invoke(cli, ["net-worth"], obj=session_factory)
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[-2:] == ["Net worth (at market): 1000.00", "0 of 0 holdings estimated"]


def test_net_worth_summary_on_a_mixed_ledger(session_factory: sessionmaker, mixed_ledger: None) -> None:
    result = CliRunner().invoke(cli, ["net-worth"], obj=session_factory)
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[-2:] == [
        "Net worth (at market): 1050.00",
        "2 of 3 holdings estimated (1 stale, 1 at cost)",
    ]


@pytest.mark.parametrize("value", ["-1", "x"])
def test_net_worth_rejects_an_invalid_max_age_days(value: str) -> None:
    def forbidden_factory():
        raise AssertionError("no session may be opened for an invalid --max-age-days")

    result = CliRunner().invoke(cli, ["net-worth", "--max-age-days", value], obj=forbidden_factory)
    assert result.exit_code == 2
    assert "--max-age-days" in result.output


@pytest.mark.parametrize("max_age", [7, 3, 0])
def test_net_worth_max_age_days_boundary(
    session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch, max_age: int
) -> None:
    today = date(2026, 6, 15)

    class PinnedDate(date):
        @classmethod
        def today(cls) -> "PinnedDate":
            return cls(today.year, today.month, today.day)

    monkeypatch.setattr("kohle.app.cli.cli.date", PinnedDate)
    with session_factory() as session:
        ctx = DbTransactionContext(session)
        AddAccount(session).execute(PEOPLE_ROOT, AccountType.asset).unwrap()
        depot = add_account_service(ctx, "Depot", AccountType.asset, "DE2").unwrap()
        cash = add_account_service(ctx, "Cash", AccountType.income).unwrap()
        eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap()
        units = {
            name: add_unit_service(ctx, name, name, UnitKind.security).unwrap() for name in ("EDGE", "PAST")
        }
        for name, unit in units.items():
            add_journal_entry_service(
                ctx, date(2026, 3, 2), f"buy-{name}", f"buy {name}",
                [
                    LineSpec(depot.id, unit.id, Decimal(1), Decimal(10), is_debit=True),
                    LineSpec(cash.id, eur.id, Decimal(10), EUR, is_debit=False),
                ],
            ).unwrap()
        session.add(Price(unit_id=units["EDGE"].id, price_date=today - timedelta(days=max_age), price=Decimal(12), source="file"))
        session.add(Price(unit_id=units["PAST"].id, price_date=today - timedelta(days=max_age + 1), price=Decimal(12), source="file"))
        session.commit()

    args = ["net-worth", "--max-age-days", str(max_age)]
    result = CliRunner().invoke(cli, args, obj=session_factory)
    assert result.exit_code == 0, result.output
    edge_row = next(r for r in result.output.splitlines() if " EDGE " in r)
    past_row = next(r for r in result.output.splitlines() if " PAST " in r)
    assert "fresh" in edge_row
    assert "stale" in past_row


def test_net_worth_max_age_days_midrange(session_factory: sessionmaker, mixed_ledger: None) -> None:
    # FRESH is 1 day old and STALE 30: N=10 keeps the first fresh, N=0 makes it stale,
    # N=60 makes the second fresh. None sits within a day of N.
    def statuses(max_age: int) -> tuple[bool, bool]:
        result = CliRunner().invoke(cli, ["net-worth", "--max-age-days", str(max_age)], obj=session_factory)
        assert result.exit_code == 0, result.output
        rows = result.output.splitlines()
        fresh = next(r for r in rows if " FRESH " in r)
        stale = next(r for r in rows if " STALE " in r)
        return ("fresh" in fresh, "fresh" in stale)

    assert statuses(10) == (True, False)
    assert statuses(60) == (True, True)
    assert statuses(0) == (False, False)


def test_balance_columns_and_restatement_row(session_factory: sessionmaker, mixed_ledger: None) -> None:
    result = CliRunner().invoke(cli, ["balance", "Depot"], obj=session_factory)
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0].split() == [
        "unit", "quantity", "price", "price", "date", "market", "value", "status", "average", "cost",
    ]
    fresh_row = next(r for r in lines if r.startswith("FRESH"))
    assert "12.00" in fresh_row and "120.00" in fresh_row and "fresh" in fresh_row
    assert fresh_row.split()[-1] == "10.00"

    euro_only = CliRunner().invoke(cli, ["balance", "Alice"], obj=session_factory)
    assert euro_only.exit_code == 0, euro_only.output
    total_row = next(r for r in euro_only.output.splitlines() if r.startswith("Total (base currency)"))
    assert total_row.split()[3:] == ["16.00", "-", "-", "16.00", "-", "-"]


def _euro_and_securities(session_factory: sessionmaker, held: str | None, sold: str | None) -> None:
    """Account `Box` holds euros, plus `held` bought and `sold` bought then sold out."""
    with session_factory() as session:
        ctx = DbTransactionContext(session)
        box = add_account_service(ctx, "Box", AccountType.asset).unwrap()
        income = add_account_service(ctx, "Income", AccountType.income).unwrap()
        eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap()
        add_journal_entry_service(
            ctx, date(2026, 3, 1), "in", "in",
            [
                LineSpec(box.id, eur.id, Decimal(100), EUR, is_debit=True),
                LineSpec(income.id, eur.id, Decimal(100), EUR, is_debit=False),
            ],
        ).unwrap()
        for name in (held, sold):
            if name is None:
                continue
            unit = add_unit_service(ctx, name, name, UnitKind.security).unwrap()
            add_journal_entry_service(
                ctx, date(2026, 3, 2), f"buy-{name}", f"buy {name}",
                [
                    LineSpec(box.id, unit.id, Decimal(2), Decimal(10), is_debit=True),
                    LineSpec(box.id, eur.id, Decimal(20), EUR, is_debit=False),
                ],
            ).unwrap()
            if name == sold:
                add_journal_entry_service(
                    ctx, date(2026, 3, 3), f"sell-{name}", f"sell {name}",
                    [
                        LineSpec(box.id, eur.id, Decimal(20), EUR, is_debit=True),
                        LineSpec(box.id, unit.id, Decimal(2), Decimal(10), is_debit=False),
                    ],
                ).unwrap()
            if name == held:
                session.flush()
                session.add(Price(unit_id=unit.id, price_date=date.today() - timedelta(days=1), price=Decimal(12), source="file"))  # noqa: DTZ011
        session.commit()


def test_balance_market_lines_only_for_non_base_holdings(session_factory: sessionmaker, mixed_ledger: None) -> None:
    def run(account: str) -> list[str]:
        result = CliRunner().invoke(cli, ["balance", account], obj=session_factory)
        assert result.exit_code == 0, result.output
        return result.output.splitlines()

    euro_only = run("Alice")
    assert "Market value" not in "\n".join(euro_only) and "holdings estimated" not in "\n".join(euro_only)
    assert euro_only[-1].startswith("Total (base currency)")

    mixed = run("Depot")
    assert mixed[-3] == ""
    assert mixed[-2:] == ["Market value: 320.00", "2 of 3 holdings estimated (1 stale, 1 at cost)"]
    # unit rows only: 120 + 180 + 20.
    assert "Total (base currency)" not in "\n".join(mixed)

    assert run("Salary")[0].startswith("unit")


def test_balance_market_line_with_no_estimates(session_factory: sessionmaker) -> None:
    _euro_and_securities(session_factory, held="HELD", sold=None)
    result = CliRunner().invoke(cli, ["balance", "Box"], obj=session_factory)
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[-2:] == ["Market value: 104.00", "0 of 1 holdings estimated"]


def test_balance_market_lines_not_printed_when_only_non_base_row_is_sold_out(session_factory: sessionmaker) -> None:
    # REGRESSION: the gate is M (nonzero non-base rows), not "any non-base row".
    _euro_and_securities(session_factory, held=None, sold="GONE")
    result = CliRunner().invoke(cli, ["balance", "Box"], obj=session_factory)
    assert result.exit_code == 0, result.output
    assert "GONE" in result.output
    assert "Market value" not in result.output and "holdings estimated" not in result.output


def test_balance_no_holdings_is_unchanged(session_factory: sessionmaker) -> None:
    with session_factory() as session:
        add_account_service(DbTransactionContext(session), "Empty", AccountType.asset).unwrap()
        session.commit()
    result = CliRunner().invoke(cli, ["balance", "Empty"], obj=session_factory)
    assert result.exit_code == 0, result.output
    assert result.output == "No holdings\n"


@pytest.mark.parametrize("value", ["-1", "x"])
def test_balance_rejects_an_invalid_max_age_days(value: str) -> None:
    def forbidden_factory():
        raise AssertionError("no session may be opened for an invalid --max-age-days")

    result = CliRunner().invoke(cli, ["balance", "Depot", "--max-age-days", value], obj=forbidden_factory)
    assert result.exit_code == 2
    assert "--max-age-days" in result.output


def test_balance_max_age_days(session_factory: sessionmaker, mixed_ledger: None) -> None:
    # FRESH is 1 day old and STALE 30; neither sits within a day of N.
    def statuses(max_age: int) -> tuple[bool, bool]:
        result = CliRunner().invoke(cli, ["balance", "Depot", "--max-age-days", str(max_age)], obj=session_factory)
        assert result.exit_code == 0, result.output
        rows = result.output.splitlines()
        fresh = next(r for r in rows if r.startswith("FRESH"))
        stale = next(r for r in rows if r.startswith("STALE"))
        return ("fresh" in fresh, "fresh" in stale)

    assert statuses(10) == (True, False)
    assert statuses(60) == (True, True)
    assert statuses(0) == (False, False)
