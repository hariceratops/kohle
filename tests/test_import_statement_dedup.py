"""ImportStatement dedup and atomicity (issue 026)."""

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from kohle.app.cli.cli import cli
from kohle.app.plugins.kohle_synthetic_broker_importer import (
    SyntheticBrokerStatementImporter,
)
from kohle.domain.domain_errors import (
    DuplicateReferenceInStatement,
    MalformedStatementRow,
)
from kohle.domain.models import (
    Account,
    AccountType,
    Classification,
    JournalEntry,
    JournalLine,
    Operation,
    OperationGroup,
    Unit,
)
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.journal import ImportStatement

_TABLES = (JournalEntry, JournalLine, Classification, Unit, Account, OperationGroup, Operation)


def _snapshot(session: Session) -> list[tuple[int, int | None]]:
    return [
        (
            session.scalar(select(func.count()).select_from(table)),
            session.scalar(select(func.max(table.id))),
        )
        for table in _TABLES
    ]


def _rows(cash_rows, statement_row):
    return cash_rows([
        statement_row(date(2026, 3, 1), -10.0, "Aldi", "ALDI", None),
        statement_row(date(2026, 3, 2), 50.0, "Gift", "Mum", None),
    ])


def _accounts(session: Session, *names: str) -> None:
    for name in names:
        AddAccount(session).execute(name, AccountType.asset)


def test_reimport_writes_nothing(session: Session, cash_rows, statement_row) -> None:
    _accounts(session, "Checking")
    rows = _rows(cash_rows, statement_row)
    assert ImportStatement(session).execute("Checking", rows).unwrap() == 2
    before = _snapshot(session)

    assert ImportStatement(session).execute("Checking", rows).unwrap() == 0

    assert _snapshot(session) == before


def test_the_entry_reference_is_scoped_by_account_id(session: Session, cash_rows, statement_row) -> None:
    checking = AddAccount(session).execute("Checking", AccountType.asset).unwrap()
    rows = cash_rows([statement_row(date(2026, 3, 1), -10.0, "Aldi", reference="  T-1  ")])

    ImportStatement(session).execute("Checking", rows).unwrap()

    assert session.scalar(select(JournalEntry.reference)) == f"{checking.id}:T-1"


def test_the_same_rows_into_two_accounts_are_distinct_entries(
    session: Session, cash_rows, statement_row
) -> None:
    _accounts(session, "Checking", "Savings")
    rows = _rows(cash_rows, statement_row)

    assert ImportStatement(session).execute("Checking", rows).unwrap() == 2
    assert ImportStatement(session).execute("Savings", rows).unwrap() == 2

    assert session.scalar(select(func.count()).select_from(JournalEntry)) == 4


def test_enriching_the_counterparty_does_not_reimport(session: Session, cash_rows, statement_row) -> None:
    _accounts(session, "Checking")
    rows = cash_rows([statement_row(date(2026, 3, 1), -10.0, "Aldi", reference="T-1")])
    ImportStatement(session).execute("Checking", rows).unwrap()

    enriched = [replace(rows[0], counterparty_name="ALDI SUED", counterparty_iban="DE89370400440532013000")]

    assert ImportStatement(session).execute("Checking", enriched).unwrap() == 0


@pytest.mark.parametrize("reference", ["", "   ", None])
def test_an_absent_reference_rejects_the_import_and_writes_nothing(
    session: Session, cash_rows, statement_row, reference
) -> None:
    _accounts(session, "Checking")
    rows = _rows(cash_rows, statement_row)
    rows[1] = replace(rows[1], reference=reference)
    before = _snapshot(session)

    error = ImportStatement(session).execute("Checking", rows).unwrap_err()

    assert isinstance(error, MalformedStatementRow)
    assert _snapshot(session) == before


def test_a_duplicate_reference_in_the_file_rejects_the_import(
    session: Session, cash_rows, statement_row
) -> None:
    _accounts(session, "Checking")
    rows = cash_rows([
        statement_row(date(2026, 3, 1), -10.0, "Aldi", reference="T-1"),
        statement_row(date(2026, 3, 2), -20.0, "Lidl", reference="T-1"),
    ])
    before = _snapshot(session)

    error = ImportStatement(session).execute("Checking", rows).unwrap_err()

    assert isinstance(error, DuplicateReferenceInStatement)
    assert _snapshot(session) == before


def test_a_malformed_last_row_imports_none_of_the_preceding_rows(
    session: Session, cash_rows, statement_row
) -> None:
    _accounts(session, "Checking")
    rows = cash_rows([
        statement_row(date(2026, 3, 1), -10.0, "Aldi"),
        statement_row(date(2026, 3, 2), -20.0, "Lidl"),
        statement_row(date(2026, 3, 3), -30.0, "Rewe"),
    ])
    rows[2] = replace(rows[2], reference="  ")
    before = _snapshot(session)

    assert ImportStatement(session).execute("Checking", rows).is_err

    assert _snapshot(session) == before


def test_a_row_that_fails_mid_loop_rolls_back_the_earlier_rows(
    session: Session, cash_rows, statement_row
) -> None:
    _accounts(session, "Checking")
    rows = _rows(cash_rows, statement_row)
    rows[1] = replace(rows[1], amount=None)
    before = _snapshot(session)

    assert ImportStatement(session).execute("Checking", rows).is_err

    assert _snapshot(session) == before


def test_a_failing_plugin_writes_nothing(
    session_factory: sessionmaker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with session_factory() as setup:
        _accounts(setup, "Checking")
        before = _snapshot(setup)
    statement = tmp_path / "bad.csv"
    statement.write_text("date,reference,type,isin,quantity,price,amount\n2026-03-02,T-1,split,X,1,1,\n")
    monkeypatch.setattr(
        "kohle.app.cli.cli.load_plugins",
        lambda: {"kohle-synthetic-broker": SyntheticBrokerStatementImporter()},
    )

    result = CliRunner().invoke(
        cli, ["import-statement", "kohle-synthetic-broker", "Checking", str(statement)], obj=session_factory
    )

    assert result.exit_code != 0
    assert "split" in result.output
    with session_factory() as after:
        assert _snapshot(after) == before
