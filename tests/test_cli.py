"""Layer 4 — CLI tests through Click's CliRunner.

Issue 009 wires the session factory onto Click's context object, so a
`CliRunner` invocation can be pointed at the `session_factory` fixture
instead of the real `kohle.db`. This layer covers what the layers below
cannot: that a domain error reaches the user as a message rather than a
traceback, and that output renders the way the acceptance criteria describe.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest
from click.testing import CliRunner
from sqlalchemy.orm import sessionmaker

from kohle.app.cli.cli import cli
from kohle.domain.models import Account, AccountType, UnitKind
from kohle.services.journal_services import LineSpec
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.journal import RecordJournalEntry
from kohle.use_cases.units import AddUnit


def test_injected_factory_is_used_and_real_db_is_untouched(
    session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_session_local():
        raise AssertionError("session_local must not be called when a factory is injected via obj")

    monkeypatch.setattr("kohle.app.cli.cli.session_local", forbidden_session_local)

    runner = CliRunner()
    result = runner.invoke(cli, ["add-account", "Alice", "--type", "asset"], obj=session_factory)

    assert result.exit_code == 0
    assert "Added account Alice" in result.output

    session = session_factory()
    try:
        accounts = session.query(Account).all()
        assert [a.name for a in accounts] == ["Alice"]
    finally:
        session.close()


def test_default_obj_falls_back_to_session_local(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel_factory = Mock(side_effect=lambda: Mock())
    monkeypatch.setattr("kohle.app.cli.cli.session_local", sentinel_factory)

    runner = CliRunner()
    runner.invoke(cli, ["list-accounts"])

    assert sentinel_factory.called


def test_record_posts_an_entry_and_reports_success(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-account", "Unallocated", "--type", "asset"], obj=session_factory)

    result = runner.invoke(
        cli,
        ["record", "2026-03-01", "Withdraw cash", "200", "--from", "Checking", "--to", "Unallocated"],
        obj=session_factory,
    )

    assert result.exit_code == 0
    assert "200" in result.output
    assert "EUR" in result.output
    assert "credited Checking" in result.output
    assert "debited Unallocated" in result.output


def test_record_unknown_account_prints_readable_message(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)

    result = runner.invoke(
        cli,
        ["record", "2026-03-01", "Withdraw cash", "200", "--from", "Checking", "--to", "Nope"],
        obj=session_factory,
    )

    assert result.exception is None
    assert "Failed: Account Nope not found" in result.output


def test_balance_renders_one_row_per_unit(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-account", "Groceries", "--type", "expense"], obj=session_factory)
    runner.invoke(
        cli,
        ["record", "2026-03-01", "Aldi", "80", "--from", "Checking", "--to", "Groceries"],
        obj=session_factory,
    )

    result = runner.invoke(cli, ["balance", "Groceries"], obj=session_factory)

    assert result.exit_code == 0
    assert "EUR" in result.output
    assert "80" in result.output


def test_balance_shows_total_row_for_single_base_currency_unit(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-account", "Groceries", "--type", "expense"], obj=session_factory)
    runner.invoke(
        cli,
        ["record", "2026-03-01", "Aldi", "80", "--from", "Checking", "--to", "Groceries"],
        obj=session_factory,
    )

    result = runner.invoke(cli, ["balance", "Groceries"], obj=session_factory)

    assert result.exit_code == 0
    assert "Total (base currency)" in result.output


def test_balance_omits_total_row_for_multiple_units(session_factory: sessionmaker) -> None:
    # An account holding two units must not print a total row: the check
    # only applies when there's exactly one unit and it is the base
    # currency. A simplification to "any base-currency row present" would
    # regress this case silently.
    session = session_factory()
    try:
        broker = AddAccount(session).execute("Broker", AccountType.asset).unwrap()
        checking = AddAccount(session).execute("Checking", AccountType.asset).unwrap()
        eur = AddUnit(session).execute("EUR", "Euro", UnitKind.currency).unwrap()
        share = AddUnit(session).execute("IE00B4L5Y983", "Core MSCI World", UnitKind.security).unwrap()
        RecordJournalEntry(session).execute(
            date(2026, 3, 6), "buy-1", "Buy ETF",
            [
                LineSpec(broker.id, share.id, Decimal(10), Decimal(100), is_debit=True),
                LineSpec(checking.id, eur.id, Decimal(1000), Decimal(1), is_debit=False),
            ],
        )
        RecordJournalEntry(session).execute(
            date(2026, 3, 7), "dep-1", "Deposit EUR",
            [
                LineSpec(broker.id, eur.id, Decimal(50), Decimal(1), is_debit=True),
                LineSpec(checking.id, eur.id, Decimal(50), Decimal(1), is_debit=False),
            ],
        )
    finally:
        session.close()

    runner = CliRunner()
    result = runner.invoke(cli, ["balance", "Broker"], obj=session_factory)

    assert result.exit_code == 0
    assert "IE00B4L5Y983" in result.output
    assert "Total" not in result.output


def test_balance_empty_account_prints_no_holdings(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Groceries", "--type", "expense"], obj=session_factory)

    result = runner.invoke(cli, ["balance", "Groceries"], obj=session_factory)

    assert result.exit_code == 0
    assert "No holdings" in result.output


def test_record_cross_unit_purchase_posts_the_etf_example(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-account", "Broker", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-unit", "IE00B4L5Y983", "Core MSCI World"], obj=session_factory)

    result = runner.invoke(
        cli,
        [
            "record", "2026-03-06", "Buy ETF", "10",
            "--from", "Checking", "--to", "Broker",
            "--to-unit", "IE00B4L5Y983", "--to-price", "100",
        ],
        obj=session_factory,
    )

    assert result.exit_code == 0
    assert result.exception is None

    balance_result = runner.invoke(cli, ["balance", "Broker"], obj=session_factory)
    assert "IE00B4L5Y983" in balance_result.output
    assert "10" in balance_result.output


def test_record_cross_unit_sale_is_expressible(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Broker", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-unit", "IE00B4L5Y983", "Core MSCI World"], obj=session_factory)

    result = runner.invoke(
        cli,
        [
            "record", "2026-04-20", "Sell ETF", "10",
            "--from", "Broker", "--to", "Checking",
            "--from-unit", "IE00B4L5Y983", "--from-price", "110",
        ],
        obj=session_factory,
    )

    assert result.exit_code == 0
    assert result.exception is None


def test_record_rejects_both_from_unit_and_to_unit(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-account", "Broker", "--type", "asset"], obj=session_factory)

    result = runner.invoke(
        cli,
        [
            "record", "2026-03-06", "Buy ETF", "10",
            "--from", "Checking", "--to", "Broker",
            "--from-unit", "USD", "--to-unit", "IE00B4L5Y983",
        ],
        obj=session_factory,
    )

    assert result.exit_code == 2
    assert "only one of --from-unit / --to-unit" in result.output


def test_record_rejects_to_price_without_to_unit(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-account", "Broker", "--type", "asset"], obj=session_factory)

    result = runner.invoke(
        cli,
        [
            "record", "2026-03-06", "Buy ETF", "10",
            "--from", "Checking", "--to", "Broker",
            "--to-price", "100",
        ],
        obj=session_factory,
    )

    assert result.exit_code == 2
    assert "--to-price requires --to-unit" in result.output


def test_record_rejects_from_price_without_from_unit(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-account", "Broker", "--type", "asset"], obj=session_factory)

    result = runner.invoke(
        cli,
        [
            "record", "2026-04-20", "Sell ETF", "10",
            "--from", "Broker", "--to", "Checking",
            "--from-price", "110",
        ],
        obj=session_factory,
    )

    assert result.exit_code == 2
    assert "--from-price requires --from-unit" in result.output


def test_placeholder(session_factory: sessionmaker) -> None:
    # TODO: a non-zero exit code accompanies a failed command
    # TODO: record-split with a malformed --line names the offending value
    # TODO: list-accounts renders nesting with |- connectors, since tabulate
    #       strips leading whitespace (issue 007)
    # TODO: the operations command lists the audit trail (issue 008)
    assert True
