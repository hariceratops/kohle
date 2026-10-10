from datetime import date
from decimal import Decimal

import pandas as pd
from sqlalchemy.orm import Session

from kohle.domain.domain_errors import (
    AccountNotFoundError,
    DataframeMissingColumn,
    EmptyEntry,
    EndDatePrecedesStartDateError,
    PostingToNonLeafAccount,
    UnbalancedEntry,
)
from kohle.domain.models import AccountType, UnitKind
from kohle.services.journal_services import LineSpec
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.journal import (
    UNCLASSIFIED_EXPENSE,
    UNCLASSIFIED_INCOME,
    ImportStatement,
    QueryJournalByPeriod,
    RecordJournalEntry,
)
from kohle.use_cases.units import AddUnit


def _accounts_and_units(session: Session) -> tuple[int, int, int]:
    checking = AddAccount(session).execute("Checking", AccountType.asset, "DE1").unwrap()
    groceries = AddAccount(session).execute("Groceries", AccountType.expense).unwrap()
    eur = AddUnit(session).execute("EUR", "Euro", UnitKind.currency).unwrap()
    return checking.id, groceries.id, eur.id


def test_record_balanced_entry(session: Session) -> None:
    checking_id, groceries_id, eur_id = _accounts_and_units(session)
    result = RecordJournalEntry(session).execute(
        date(2026, 3, 1), "ref-1", "Aldi",
        [
            LineSpec(groceries_id, eur_id, Decimal(80), Decimal(1), is_debit=True),
            LineSpec(checking_id, eur_id, Decimal(80), Decimal(1), is_debit=False),
        ],
    )
    assert result.is_ok
    assert len(result.unwrap().lines) == 2


def test_unbalanced_entry_rejected(session: Session) -> None:
    checking_id, groceries_id, eur_id = _accounts_and_units(session)
    result = RecordJournalEntry(session).execute(
        date(2026, 3, 1), "ref-1", "Aldi",
        [
            LineSpec(groceries_id, eur_id, Decimal(80), Decimal(1), is_debit=True),
            LineSpec(checking_id, eur_id, Decimal(70), Decimal(1), is_debit=False),
        ],
    )
    assert result.is_err
    assert isinstance(result.unwrap_err(), UnbalancedEntry)


def test_single_line_entry_rejected(session: Session) -> None:
    _, groceries_id, eur_id = _accounts_and_units(session)
    result = RecordJournalEntry(session).execute(
        date(2026, 3, 1), "ref-1", "Aldi",
        [LineSpec(groceries_id, eur_id, Decimal(80), Decimal(1), is_debit=True)],
    )
    assert result.is_err
    assert isinstance(result.unwrap_err(), EmptyEntry)


def test_cross_unit_entry_balances_on_value(session: Session) -> None:
    checking_id, _, eur_id = _accounts_and_units(session)
    broker = AddAccount(session).execute("Broker", AccountType.asset, "DE2").unwrap()
    share = AddUnit(session).execute("IE00B4L5Y983", "Core MSCI World", UnitKind.security).unwrap()

    result = RecordJournalEntry(session).execute(
        date(2026, 3, 1), "buy-1", "Bought 10 shares",
        [
            LineSpec(broker.id, share.id, Decimal(10), Decimal(100), is_debit=True),
            LineSpec(checking_id, eur_id, Decimal(1000), Decimal(1), is_debit=False),
        ],
    )
    assert result.is_ok


def test_posting_to_parent_rejected(session: Session) -> None:
    checking_id, groceries_id, eur_id = _accounts_and_units(session)
    AddAccount(session).execute("Holiday", AccountType.asset, None, "Checking")

    result = RecordJournalEntry(session).execute(
        date(2026, 3, 1), "ref-1", "Aldi",
        [
            LineSpec(groceries_id, eur_id, Decimal(80), Decimal(1), is_debit=True),
            LineSpec(checking_id, eur_id, Decimal(80), Decimal(1), is_debit=False),
        ],
    )
    assert result.is_err
    assert isinstance(result.unwrap_err(), PostingToNonLeafAccount)


def _statement() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "description": ["Aldi", "Salary"],
            "amount": [-80.0, 2500.0],
            "date": pd.to_datetime(["2026-03-05", "2026-03-01"]),
            "counterparty_name": ["ALDI SUED", "ACME GmbH"],
            "counterparty_iban": ["DE89370400440532013000", "DE02120300000000202051"],
        }
    ).astype({"counterparty_name": "string", "counterparty_iban": "string"})


def test_import_statement_creates_balanced_entries(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")

    result = ImportStatement(session).execute("Checking", _statement())
    assert result.is_ok
    assert result.unwrap() == 2

    lines = QueryJournalByPeriod(session).execute("Checking", "2026-02-01", "2026-04-01")
    assert lines.is_ok
    checking_lines = lines.unwrap()
    assert len(checking_lines) == 2
    # Money out is a credit on the asset account, money in a debit.
    assert {line.is_debit for line in checking_lines} == {True, False}
    assert all(line.unit.identifier == "EUR" for line in checking_lines)


def test_import_statement_routes_by_sign(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    ImportStatement(session).execute("Checking", _statement())

    expense_lines = QueryJournalByPeriod(session).execute(
        UNCLASSIFIED_EXPENSE, "2026-02-01", "2026-04-01"
    )
    income_lines = QueryJournalByPeriod(session).execute(
        UNCLASSIFIED_INCOME, "2026-02-01", "2026-04-01"
    )
    assert [line.value for line in expense_lines.unwrap()] == [Decimal(80)]
    assert [line.value for line in income_lines.unwrap()] == [Decimal(2500)]


def test_import_statement_is_idempotent(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    assert ImportStatement(session).execute("Checking", _statement()).unwrap() == 2
    assert ImportStatement(session).execute("Checking", _statement()).unwrap() == 0


def test_same_rows_import_into_two_accounts(session: Session) -> None:
    """The reference is per account, so an identical row on another account's
    statement is not mistaken for a duplicate."""
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    AddAccount(session).execute("Savings", AccountType.asset, "DE2")
    assert ImportStatement(session).execute("Checking", _statement()).unwrap() == 2
    assert ImportStatement(session).execute("Savings", _statement()).unwrap() == 2


def test_import_into_parent_account_rejected(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    AddAccount(session).execute("Holiday", AccountType.asset, None, "Checking")

    result = ImportStatement(session).execute("Checking", _statement())
    assert result.is_err
    assert isinstance(result.unwrap_err(), PostingToNonLeafAccount)


def test_import_statement_unknown_account(session: Session) -> None:
    result = ImportStatement(session).execute("Nope", _statement())
    assert result.is_err
    assert isinstance(result.unwrap_err(), AccountNotFoundError)


def test_import_statement_missing_column(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    df = _statement().drop(columns=["counterparty_iban"])
    result = ImportStatement(session).execute("Checking", df)
    assert result.is_err
    assert isinstance(result.unwrap_err(), DataframeMissingColumn)


def test_query_rejects_reversed_period(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    result = QueryJournalByPeriod(session).execute("Checking", "2026-04-01", "2026-02-01")
    assert result.is_err
    assert isinstance(result.unwrap_err(), EndDatePrecedesStartDateError)
