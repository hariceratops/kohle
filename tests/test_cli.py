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
from kohle.domain.models import (
    Account,
    AccountType,
    Classification,
    JournalEntry,
    JournalLine,
    Operation,
    OperationGroup,
    UnitKind,
)
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

    assert result.exit_code == 1
    assert "Error: Account 'Nope' not found" in result.output


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
    assert "average cost" in result.output
    assert "1.00" in result.output


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


def test_balance_renders_none_average_cost_as_dash_without_breaking_other_rows(
    session_factory: sessionmaker,
) -> None:
    # A base-currency account produces both a numeric average-cost row (the
    # unit row, average 1) and a None one (the total row) in the same table.
    # A mixed-type column would make tabulate drop floatfmt for the whole
    # column (regression: EUR row would render "1.00000000" instead of
    # "1.00") — passing None through with missingval avoids that.
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
    lines = result.output.splitlines()
    unit_row = next(line for line in lines if line.startswith("EUR"))
    total_row = next(line for line in lines if "Total" in line)
    assert unit_row.split()[-1] == "1.00"
    assert total_row.split()[-1] == "-"


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
    assert "100.00" in balance_result.output


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


def test_record_rejects_to_unit_without_to_price(session_factory: sessionmaker) -> None:
    # Regression guard: --to-unit alone must not silently default the price
    # to 1 — that books a security at a nonsense price and still balances.
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-account", "Broker", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-unit", "IE00B4L5Y983", "Core MSCI World"], obj=session_factory)

    result = runner.invoke(
        cli,
        [
            "record", "2026-03-06", "Buy ETF", "10",
            "--from", "Checking", "--to", "Broker",
            "--to-unit", "IE00B4L5Y983",
        ],
        obj=session_factory,
    )

    assert result.exit_code == 2
    assert "--to-unit requires --to-price" in result.output


def test_record_rejects_from_unit_without_from_price(session_factory: sessionmaker) -> None:
    # Regression guard, sale direction: --from-unit alone must not silently
    # default the price to 1 either.
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Broker", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-unit", "IE00B4L5Y983", "Core MSCI World"], obj=session_factory)

    result = runner.invoke(
        cli,
        [
            "record", "2026-04-20", "Sell ETF", "10",
            "--from", "Broker", "--to", "Checking",
            "--from-unit", "IE00B4L5Y983",
        ],
        obj=session_factory,
    )

    assert result.exit_code == 2
    assert "--from-unit requires --from-price" in result.output


def test_record_split_posts_a_three_way_shared_expense(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-account", "Alice", "--type", "expense"], obj=session_factory)
    runner.invoke(cli, ["add-account", "Bob", "--type", "expense"], obj=session_factory)
    runner.invoke(cli, ["add-unit", "EUR", "Euro"], obj=session_factory)

    result = runner.invoke(
        cli,
        [
            "record-split", "2026-03-01", "Dinner split three ways",
            "--line", "Checking:90:EUR:1:credit",
            "--line", "Alice:45:EUR:1:debit",
            "--line", "Bob:45:EUR:1:debit",
        ],
        obj=session_factory,
    )

    assert result.exit_code == 0
    assert result.exception is None
    assert "3 lines" in result.output


def test_record_split_fewer_than_two_lines_surfaces_empty_entry_readably(
    session_factory: sessionmaker,
) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-unit", "EUR", "Euro"], obj=session_factory)

    result = runner.invoke(
        cli,
        ["record-split", "2026-03-01", "Dinner", "--line", "Checking:90:EUR:1:credit"],
        obj=session_factory,
    )

    assert result.exit_code == 1
    assert "Error: Journal entry must have at least two lines" in result.output


def test_record_split_duplicate_line_surfaces_actionable_message_not_raw_sql(
    session_factory: sessionmaker,
) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-account", "Groceries", "--type", "expense"], obj=session_factory)
    runner.invoke(cli, ["add-unit", "EUR", "Euro"], obj=session_factory)

    result = runner.invoke(
        cli,
        [
            "record-split", "2026-03-01", "Aldi, entered twice instead of combined",
            "--line", "Groceries:10:EUR:1:debit",
            "--line", "Groceries:20:EUR:1:debit",
            "--line", "Checking:30:EUR:1:credit",
        ],
        obj=session_factory,
    )

    assert result.exit_code == 1
    assert "Error: Two lines on the same account, unit and side; combine them" in result.output
    assert "UNIQUE constraint" not in result.output


def test_record_split_wrong_field_count_names_the_offending_value(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["record-split", "2026-03-01", "Dinner", "--line", "Groceries:10:EUR:debit"],
        obj=session_factory,
    )

    assert result.exit_code == 2
    assert "Groceries:10:EUR:debit" in result.output


def test_record_split_bad_side_names_the_offending_value(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["record-split", "2026-03-01", "Dinner", "--line", "Groceries:10:EUR:1:dr"],
        obj=session_factory,
    )

    assert result.exit_code == 2
    assert "'dr'" in result.output


def test_record_split_non_numeric_quantity_names_the_offending_value(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["record-split", "2026-03-01", "Dinner", "--line", "Groceries:ten:EUR:1:debit"],
        obj=session_factory,
    )

    assert result.exit_code == 2
    assert "'ten'" in result.output


def test_record_split_non_numeric_price_names_the_offending_value(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["record-split", "2026-03-01", "Dinner", "--line", "Groceries:10:EUR:free:debit"],
        obj=session_factory,
    )

    assert result.exit_code == 2
    assert "'free'" in result.output


def test_list_accounts_renders_nesting_with_connectors_not_spaces(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Cash", "--type", "asset"], obj=session_factory)
    runner.invoke(
        cli, ["add-account", "Groceries", "--type", "expense", "--parent", "Cash"], obj=session_factory
    )
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)

    result = runner.invoke(cli, ["list-accounts"], obj=session_factory)

    assert result.exit_code == 0
    lines = result.output.splitlines()
    groceries_line = next(line for line in lines if "Groceries" in line)
    assert groceries_line.startswith("|- ")
    assert not groceries_line.startswith(" ")


def test_list_accounts_distinguishes_parent_from_leaf(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Cash", "--type", "asset"], obj=session_factory)
    runner.invoke(
        cli, ["add-account", "Groceries", "--type", "expense", "--parent", "Cash"], obj=session_factory
    )

    result = runner.invoke(cli, ["list-accounts"], obj=session_factory)

    lines = result.output.splitlines()
    cash_line = next(line for line in lines if line.startswith("Cash"))
    groceries_line = next(line for line in lines if "Groceries" in line)
    assert cash_line.startswith("Cash/")
    assert not groceries_line.strip().endswith("/")


def test_list_accounts_puts_parentless_accounts_at_top_level(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Cash", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)

    result = runner.invoke(cli, ["list-accounts"], obj=session_factory)

    lines = result.output.splitlines()
    assert any(line.startswith("Checking") for line in lines)
    assert any(line.startswith("Cash") for line in lines)


def test_list_accounts_renders_three_level_nesting(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Cash", "--type", "asset"], obj=session_factory)
    runner.invoke(
        cli, ["add-account", "Envelopes", "--type", "asset", "--parent", "Cash"], obj=session_factory
    )
    runner.invoke(
        cli, ["add-account", "Groceries", "--type", "expense", "--parent", "Envelopes"], obj=session_factory
    )

    result = runner.invoke(cli, ["list-accounts"], obj=session_factory)

    lines = result.output.splitlines()
    envelopes_line = next(line for line in lines if "Envelopes" in line)
    groceries_line = next(line for line in lines if "Groceries" in line)
    assert envelopes_line.startswith("|- ")
    assert groceries_line.startswith("|  |- ")


def test_list_accounts_keeps_type_and_iban_columns_visible(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(
        cli, ["add-account", "Checking", "--type", "asset", "--iban", "DE123"], obj=session_factory
    )

    result = runner.invoke(cli, ["list-accounts"], obj=session_factory)

    assert "asset" in result.output
    assert "DE123" in result.output


def test_list_accounts_with_account_argument_roots_the_tree_at_a_subtree(
    session_factory: sessionmaker,
) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Cash", "--type", "asset"], obj=session_factory)
    runner.invoke(
        cli, ["add-account", "Groceries", "--type", "expense", "--parent", "Cash"], obj=session_factory
    )
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)

    result = runner.invoke(cli, ["list-accounts", "Cash"], obj=session_factory)

    assert "Checking" not in result.output
    assert "Cash" in result.output
    assert "Groceries" in result.output


def test_list_accounts_unknown_name_reports_the_miss(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)

    result = runner.invoke(cli, ["list-accounts", "Nope"], obj=session_factory)

    assert result.exit_code == 1
    assert result.output.strip() == "Error: Account 'Nope' not found"


def test_list_accounts_empty_ledger_says_so_instead_of_printing_a_blank_line(
    session_factory: sessionmaker,
) -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["list-accounts"], obj=session_factory)

    assert result.output.strip() != ""
    assert result.output.strip() == "No accounts"


def test_failing_command_exits_non_zero_and_writes_to_stderr(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)

    result = runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)

    assert result.exit_code != 0
    assert "Error: Account Checking already exists" in result.stderr
    assert "Error: Account Checking already exists" not in result.stdout


def _data_rows(output: str) -> list[str]:
    lines = output.splitlines()
    return [
        line
        for line in lines
        if line.strip() and not set(line.strip()) <= {"-", " "} and not line.strip().startswith("group")
    ]


def test_list_operations_shows_group_entity_type_entity_id_and_action(
    session_factory: sessionmaker,
) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)

    result = runner.invoke(cli, ["list-operations"], obj=session_factory)

    assert result.exit_code == 0
    header = result.output.splitlines()[0]
    assert header.split() == ["group", "entity_type", "entity_id", "action"]
    row = _data_rows(result.output)[0]
    assert row.split() == ["1", "accounts", "1", "create"]


def test_list_operations_orders_most_recent_transaction_first_steps_in_order(
    session_factory: sessionmaker,
) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-account", "Groceries", "--type", "expense"], obj=session_factory)
    # First record auto-creates the base-currency unit inside the same
    # transaction as the entry, so its group has two steps in the order
    # they happened: the unit, then the entry that uses it.
    runner.invoke(
        cli,
        ["record", "2026-03-01", "Aldi", "80", "--from", "Checking", "--to", "Groceries"],
        obj=session_factory,
    )
    runner.invoke(
        cli,
        ["record", "2026-03-02", "Aldi again", "40", "--from", "Checking", "--to", "Groceries"],
        obj=session_factory,
    )

    result = runner.invoke(cli, ["list-operations"], obj=session_factory)

    assert result.exit_code == 0
    entity_types = [row.split()[1] for row in _data_rows(result.output)]

    assert entity_types[0] == "journal_entries"  # second, most recent record
    assert entity_types[1] == "units"  # first record's group: unit created first
    assert entity_types[2] == "journal_entries"  # ... then the entry


def test_list_operations_is_read_only(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)

    session = session_factory()
    try:
        before = session.query(Operation).count()
    finally:
        session.close()

    result = runner.invoke(cli, ["list-operations"], obj=session_factory)
    assert result.exit_code == 0

    session = session_factory()
    try:
        after = session.query(Operation).count()
    finally:
        session.close()

    assert after == before


def test_entries_in_period_shows_the_counterparty(session_factory: sessionmaker) -> None:
    # Issue 013 wants the counterparty confirmable without opening the
    # database. Seeded through the ORM rather than a CLI command because only
    # an import produces one, and that needs a plugin.
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-account", "Groceries", "--type", "expense"], obj=session_factory)

    session = session_factory()
    try:
        eur = AddUnit(session).execute("EUR", "Euro", UnitKind.currency).unwrap()
        checking = session.query(Account).filter_by(name="Checking").one()
        groceries = session.query(Account).filter_by(name="Groceries").one()
        entry = JournalEntry(
            entry_date=date(2026, 3, 5),
            reference="ref-1",
            description="Aldi",
            counterparty_name="ALDI SUED",
            counterparty_iban="DE89370400440532013000",
        )
        entry.lines = [
            JournalLine(account_id=groceries.id, unit_id=eur.id, quantity=Decimal(80),
                        unit_price=Decimal(1), is_debit=True),
            JournalLine(account_id=checking.id, unit_id=eur.id, quantity=Decimal(80),
                        unit_price=Decimal(1), is_debit=False),
        ]
        session.add(entry)
        session.commit()
    finally:
        session.close()

    result = runner.invoke(
        cli, ["entries-in-period", "Checking", "2026-03-01", "2026-04-01"], obj=session_factory
    )

    assert result.exit_code == 0
    assert "counterparty" in result.output.splitlines()[0]
    assert "ALDI SUED" in result.output


def test_entries_in_period_renders_a_missing_counterparty_as_dash(
    session_factory: sessionmaker,
) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)
    runner.invoke(cli, ["add-account", "Groceries", "--type", "expense"], obj=session_factory)
    runner.invoke(
        cli,
        ["record", "2026-03-01", "Aldi", "80", "--from", "Checking", "--to", "Groceries"],
        obj=session_factory,
    )

    result = runner.invoke(
        cli, ["entries-in-period", "Checking", "2026-02-01", "2026-04-01"], obj=session_factory
    )

    assert result.exit_code == 0
    entry_row = next(line for line in result.output.splitlines() if "Aldi" in line)
    assert entry_row.split() == ["2026-03-01", "Aldi", "-", "cr", "80.00", "EUR", "80.00"]


def test_add_rule_reports_a_malformed_pattern_without_a_traceback(
    session_factory: sessionmaker,
) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Groceries", "--type", "expense"], obj=session_factory)

    result = runner.invoke(cli, ["add-rule", "REWE[", "Groceries"], obj=session_factory)

    assert result.exit_code != 0
    assert "unterminated character set at position 4" in result.output
    assert "Traceback" not in result.output


def test_add_rule_reports_an_unknown_account(session_factory: sessionmaker) -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["add-rule", "REWE", "Grocerys"], obj=session_factory)

    assert result.exit_code != 0
    assert "Account 'Grocerys' not found" in result.output


def test_list_rules_renders_evaluation_order_with_the_id_remove_rule_takes(
    session_factory: sessionmaker,
) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Groceries", "--type", "expense"], obj=session_factory)
    runner.invoke(cli, ["add-account", "Misc", "--type", "expense"], obj=session_factory)
    runner.invoke(cli, ["add-rule", ".", "Misc", "--priority", "900"], obj=session_factory)
    runner.invoke(cli, ["add-rule", "REWE|ALDI", "Groceries", "--priority", "10"], obj=session_factory)

    result = runner.invoke(cli, ["list-rules"], obj=session_factory)

    assert result.exit_code == 0
    assert result.output.splitlines()[0].split() == ["id", "priority", "pattern", "account"]
    rows = [line.split() for line in result.output.splitlines()[2:]]
    assert rows == [["2", "10", "REWE|ALDI", "Groceries"], ["1", "900", ".", "Misc"]]


def test_list_rules_empty_says_so_instead_of_printing_a_blank_line(
    session_factory: sessionmaker,
) -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["list-rules"], obj=session_factory)

    assert result.exit_code == 0
    assert result.output.strip() == "No rules"


def test_remove_rule_drops_it_from_the_listing(session_factory: sessionmaker) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Groceries", "--type", "expense"], obj=session_factory)
    runner.invoke(cli, ["add-rule", "REWE", "Groceries"], obj=session_factory)

    result = runner.invoke(cli, ["remove-rule", "1"], obj=session_factory)

    assert result.exit_code == 0
    assert "Removed rule 1" in result.output
    assert runner.invoke(cli, ["list-rules"], obj=session_factory).output.strip() == "No rules"


def test_remove_rule_on_an_unknown_id_reports_the_miss(session_factory: sessionmaker) -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["remove-rule", "42"], obj=session_factory)

    assert result.exit_code != 0
    assert "Rule id 42 not found" in result.output


def test_list_unclassified_on_an_empty_ledger_prints_the_empty_message(
    session_factory: sessionmaker,
) -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["list-unclassified"], obj=session_factory)

    assert result.exit_code == 0
    assert result.output.strip() == "No unclassified lines"


def test_list_unclassified_is_read_only_and_leaves_no_group_behind(
    session_factory: sessionmaker,
) -> None:
    # Bucket resolution has to use the strict lookup, not
    # _get_or_create_account: with the lazy OperationGroup behaviour from
    # issue 011, a read-only command that wrote anything would leave a group.
    runner = CliRunner()

    result = runner.invoke(cli, ["list-unclassified"], obj=session_factory)
    assert result.exit_code == 0

    session = session_factory()
    try:
        assert session.query(Account).count() == 0
        assert session.query(OperationGroup).count() == 0
    finally:
        session.close()


def test_list_unclassified_shows_the_fallen_through_line(session_factory: sessionmaker) -> None:
    # Seeded through the ORM rather than through import-statement: only an
    # import produces a classification, and that needs a plugin.
    runner = CliRunner()
    runner.invoke(cli, ["add-account", "Checking", "--type", "asset"], obj=session_factory)
    runner.invoke(
        cli, ["add-account", "Unclassified Expense", "--type", "expense"], obj=session_factory
    )
    runner.invoke(
        cli, ["add-account", "Unclassified Income", "--type", "income"], obj=session_factory
    )

    session = session_factory()
    try:
        eur = AddUnit(session).execute("EUR", "Euro", UnitKind.currency).unwrap()
        checking = session.query(Account).filter_by(name="Checking").one()
        bucket = session.query(Account).filter_by(name="Unclassified Expense").one()
        entry = JournalEntry(
            entry_date=date(2026, 3, 5),
            reference="ref-1",
            description="Unknown shop",
            counterparty_name="SOME SHOP",
            counterparty_iban=None,
        )
        entry.lines = [
            JournalLine(account_id=bucket.id, unit_id=eur.id, quantity=Decimal(80),
                        unit_price=Decimal(1), is_debit=True),
            JournalLine(account_id=checking.id, unit_id=eur.id, quantity=Decimal(80),
                        unit_price=Decimal(1), is_debit=False),
        ]
        session.add(entry)
        session.flush()
        session.add(Classification(
            journal_entry_id=entry.id,
            proposed_account_id=bucket.id,
            matched_rule_id=None,
            final_account_id=bucket.id,
        ))
        session.commit()
    finally:
        session.close()

    result = runner.invoke(cli, ["list-unclassified"], obj=session_factory)

    assert result.exit_code == 0
    assert result.output.splitlines()[0].split() == [
        "entry_id", "date", "description", "counterparty", "amount", "account",
    ]
    row = next(line for line in result.output.splitlines() if "Unknown" in line)
    assert row.split() == [
        "1", "2026-03-05", "Unknown", "shop", "SOME", "SHOP", "80.00", "Unclassified", "Expense",
    ]
