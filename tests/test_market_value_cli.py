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


@pytest.mark.skip(reason="scaffold: issue 037")
def test_net_worth_max_age_days() -> None:
    # TODO(037) — one test per site:
    #   - -1 and x exit 2 with an obj= factory that fails the test if called (forbidden_session_local pattern)
    #   - boundary pair via the monkeypatched kohle.app.cli.cli.date
    #   - a mid-range check seeded relative to real date.today() with ages well away from N
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 038")
def test_balance_columns_and_restatement_row() -> None:
    # TODO(038) — one test per site:
    #   - header order: unit quantity price price date market value status average cost
    #   - 'Total (base currency)' row: '-' in price, price date, status, average cost; quantity in market value
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 038")
def test_balance_market_lines_only_for_non_base_holdings() -> None:
    # TODO(038) — one test per site:
    #   - a euro-only account (M = 0) prints neither 'Market value' nor 'holdings estimated'
    #   - a mixed account prints both as the last two lines; X is the sum of unit rows only
    #   - a mixed account with K = 0 prints '0 of M holdings estimated'
    #   - REGRESSION: an account whose only non-euro row is sold out (M = 0) prints neither line: the gate is M, not 'any non-base row'
    #   - 'No holdings' output unchanged
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 038")
def test_balance_max_age_days() -> None:
    # TODO(038) — one test per site:
    #   - same flag, same behaviour as net-worth
    raise NotImplementedError
