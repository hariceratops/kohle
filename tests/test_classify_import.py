"""Layer 3 — use-case tests against the `session` fixture.

Classification inside the import loop (issues 013, 015).

Several of these are regression guards rather than feature tests: the code they
cover is correct in a way that is easy to silently break later, and
dev/design/expense-classification.md names each one as a trap.
"""

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from kohle.domain.domain_errors import DataframeMissingColumn, PostingToNonLeafAccount
from kohle.domain.models import (
    AccountType,
    Classification,
    JournalEntry,
    Operation,
    OperationGroup,
)
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.journal import (
    ImportStatement,
    LineInput,
    QueryJournalByPeriod,
    RecordSimpleEntry,
    RecordSplitEntry,
    _optional_str,
)
from kohle.use_cases.rules import AddRule


def _ledger(session: Session) -> None:
    AddAccount(session).execute("Checking", AccountType.asset, "DE1")
    AddAccount(session).execute("Groceries", AccountType.expense)


def _entries(session: Session) -> dict:
    lines = QueryJournalByPeriod(session).execute("Checking", "2026-02-01", "2026-04-01").unwrap()
    return {line.entry.description: line.entry for line in lines}


def test_import_stores_the_counterparty(session: Session, statement_df, statement_row) -> None:
    _ledger(session)
    df = statement_df([
        statement_row(date(2026, 3, 5), -80.0, "Aldi", "ALDI SUED", "DE89370400440532013000"),
        statement_row(date(2026, 3, 1), 2500.0, "Salary", "ACME GmbH", None),
    ])

    assert ImportStatement(session).execute("Checking", df).unwrap() == 2

    entries = _entries(session)
    assert entries["Aldi"].counterparty_name == "ALDI SUED"
    assert entries["Aldi"].counterparty_iban == "DE89370400440532013000"
    # Per-row absence is normal — a card payment usually carries no
    # counterparty IBAN — and is stored as NULL rather than a placeholder.
    assert entries["Salary"].counterparty_name == "ACME GmbH"
    assert entries["Salary"].counterparty_iban is None


def test_hand_entered_entries_have_no_counterparty(session: Session) -> None:
    _ledger(session)

    simple = RecordSimpleEntry(session).execute(
        date(2026, 3, 5), "Aldi", Decimal(80), "Checking", "Groceries"
    )
    split = RecordSplitEntry(session).execute(
        date(2026, 3, 6), "Dinner",
        [
            LineInput("Groceries", Decimal(40), "EUR", Decimal(1), is_debit=True),
            LineInput("Checking", Decimal(40), "EUR", Decimal(1), is_debit=False),
        ],
    )

    for entry in (simple.unwrap(), split.unwrap()):
        assert entry.counterparty_name is None
        assert entry.counterparty_iban is None


def test_a_plugin_omitting_the_column_fails_before_any_row_is_touched(
    session: Session, statement_df, statement_row
) -> None:
    _ledger(session)
    df = statement_df([
        statement_row(date(2026, 3, 5), -80.0, "Aldi", "ALDI SUED", "DE89370400440532013000"),
    ]).drop(columns=["counterparty_name"])

    result = ImportStatement(session).execute("Checking", df)

    assert result.is_err
    err = result.unwrap_err()
    assert isinstance(err, DataframeMissingColumn)
    # The message is the contract's whole enforcement mechanism, so it names
    # the column a plugin author has to add.
    assert "counterparty_name" in str(err)
    assert _entries(session) == {}


def test_statement_with_no_counterparty_data_anywhere_imports(
    session: Session, statement_df, statement_row
) -> None:
    # REGRESSION: read_csv types a text column that is empty on every row as
    # float64, so this shape failed the schema check for the old `iban` column
    # with an error about a column the user never sees (design §3.3).
    _ledger(session)
    df = statement_df([
        statement_row(date(2026, 3, 5), -80.0, "Aldi"),
        statement_row(date(2026, 3, 1), 2500.0, "Salary"),
    ])

    assert ImportStatement(session).execute("Checking", df).unwrap() == 2
    assert all(
        entry.counterparty_name is None and entry.counterparty_iban is None
        for entry in _entries(session).values()
    )


def test_counterparty_is_not_part_of_the_reference_hash(
    session: Session, statement_df, statement_row
) -> None:
    # REGRESSION: folding the counterparty into the digest would change every
    # reference and silently re-import every statement ever imported (§3.6).
    _ledger(session)
    plain = statement_df([
        statement_row(date(2026, 3, 5), -80.0, "Aldi"),
        statement_row(date(2026, 3, 1), 2500.0, "Salary"),
    ])
    enriched = statement_df([
        statement_row(date(2026, 3, 5), -80.0, "Aldi", "ALDI SUED", "DE89370400440532013000"),
        statement_row(date(2026, 3, 1), 2500.0, "Salary", "ACME GmbH", "DE02120300000000202051"),
    ])

    assert ImportStatement(session).execute("Checking", plain).unwrap() == 2
    assert ImportStatement(session).execute("Checking", enriched).unwrap() == 0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (pd.NA, None),
        (float("nan"), None),
        ("", None),
        ("   ", None),
        ("REWE", "REWE"),
        ("  REWE SAGT DANKE  ", "REWE SAGT DANKE"),
    ],
)
def test_optional_str_normalises_a_statement_cell(value, expected) -> None:
    assert _optional_str(value) == expected


def _landing_account(session: Session, description: str) -> str:
    """The account the counterpart line of an imported row landed on."""
    entry = session.query(JournalEntry).filter(JournalEntry.description == description).one()
    return ({line.account.name for line in entry.lines} - {"Checking"}).pop()


def _classification(session: Session, description: str) -> Classification:
    return (
        session.query(Classification)
        .join(JournalEntry, Classification.journal_entry_id == JournalEntry.id)
        .filter(JournalEntry.description == description)
        .one()
    )


def _two_rows(statement_df, statement_row):
    return statement_df([
        statement_row(date(2026, 3, 5), -80.0, "ALDI SUED 1234", "ALDI SUED", None),
        statement_row(date(2026, 3, 6), -25.0, "Kiosk am Eck"),
    ])


def test_a_matched_row_posts_to_its_rule_target(session: Session, statement_df, statement_row) -> None:
    _ledger(session)
    rule = AddRule(session).execute("ALDI", "Groceries").unwrap()

    assert ImportStatement(session).execute("Checking", _two_rows(statement_df, statement_row)).unwrap() == 2

    assert _landing_account(session, "ALDI SUED 1234") == "Groceries"
    classification = _classification(session, "ALDI SUED 1234")
    assert classification.matched_rule_id == rule.id
    assert classification.final_account_id == classification.proposed_account_id
    assert classification.corrected is False


def test_a_row_matching_nothing_still_lands_in_the_bucket(
    session: Session, statement_df, statement_row
) -> None:
    _ledger(session)
    AddRule(session).execute("ALDI", "Groceries")

    assert ImportStatement(session).execute("Checking", _two_rows(statement_df, statement_row)).unwrap() == 2

    assert _landing_account(session, "Kiosk am Eck") == "Unclassified Expense"
    # Recorded on the fall-through path too, so there is one place to read
    # from whether or not a rule fired.
    classification = _classification(session, "Kiosk am Eck")
    assert classification.matched_rule_id is None
    assert classification.final_account_id == classification.proposed_account_id


def test_an_empty_rule_set_imports_exactly_as_before(
    session: Session, statement_df, statement_row
) -> None:
    _ledger(session)

    assert ImportStatement(session).execute("Checking", _two_rows(statement_df, statement_row)).unwrap() == 2

    assert _landing_account(session, "ALDI SUED 1234") == "Unclassified Expense"
    assert _landing_account(session, "Kiosk am Eck") == "Unclassified Expense"
    assert session.query(Classification).count() == 2


def test_importing_the_same_statement_twice_still_imports_nothing(
    session: Session, statement_df, statement_row
) -> None:
    _ledger(session)
    AddRule(session).execute("ALDI", "Groceries")
    df = _two_rows(statement_df, statement_row)

    assert ImportStatement(session).execute("Checking", df).unwrap() == 2
    assert ImportStatement(session).execute("Checking", df).unwrap() == 0

    assert session.query(Classification).count() == 2


def test_a_rule_target_that_has_gained_a_child_fails_the_import(
    session: Session, statement_df, statement_row
) -> None:
    # Posting still goes through post_entry, so leaf-only posting is enforced
    # by validate_lines rather than reimplemented here. Failing loudly beats
    # falling back to the bucket: a silent fallback would leave the user's
    # rules disabled with nothing saying why (design §5.3).
    _ledger(session)
    AddRule(session).execute("ALDI", "Groceries")
    AddAccount(session).execute("Organic", AccountType.expense, parent_name="Groceries")

    result = ImportStatement(session).execute("Checking", _two_rows(statement_df, statement_row))

    assert result.is_err
    assert isinstance(result.unwrap_err(), PostingToNonLeafAccount)


def test_one_import_produces_one_group_holding_every_write(
    session_factory: sessionmaker, statement_df, statement_row
) -> None:
    # REGRESSION: guards against the classifier being written as a UnitOfWork,
    # which would commit and close the session on the first row and leave the
    # statement half-imported (design §5.2).
    AddAccount(session_factory()).execute("Checking", AccountType.asset, "DE1")
    AddAccount(session_factory()).execute("Groceries", AccountType.expense)
    AddRule(session_factory()).execute("ALDI", "Groceries")

    with session_factory() as session:
        groups_before = session.scalar(select(func.count()).select_from(OperationGroup))

    assert ImportStatement(session_factory()).execute(
        "Checking", _two_rows(statement_df, statement_row)
    ).unwrap() == 2

    with session_factory() as session:
        groups = session.scalars(select(OperationGroup.id).order_by(OperationGroup.id)).all()
        import_ops = session.scalars(
            select(Operation).where(Operation.group_id == groups[-1])
        ).all()

    assert len(groups) == groups_before + 1
    # One group per use-case run, not per row: the EUR unit, both bucket
    # accounts, both entries and both classifications are one logical write.
    assert {op.entity_type for op in import_ops} >= {"units", "accounts", "journal_entries", "classifications"}
    assert len([op for op in import_ops if op.entity_type == "classifications"]) == 2


def test_a_row_failing_mid_import_leaves_nothing_behind(
    session_factory: sessionmaker, statement_df, statement_row
) -> None:
    # REGRESSION: atomicity asserted rather than assumed. A partial commit
    # would leave entries with no classification — invisible to
    # list-unclassified, and so permanently lost.
    AddAccount(session_factory()).execute("Checking", AccountType.asset, "DE1")
    AddAccount(session_factory()).execute("Groceries", AccountType.expense)
    AddAccount(session_factory()).execute("Kiosk", AccountType.expense)
    AddRule(session_factory()).execute("ALDI", "Groceries")
    AddRule(session_factory()).execute("Kiosk", "Kiosk")
    # The second row's rule target stops being a leaf, so the import fails
    # after the first row has already been written.
    AddAccount(session_factory()).execute("Snacks", AccountType.expense, parent_name="Kiosk")

    with session_factory() as session:
        groups_before = session.scalar(select(func.count()).select_from(OperationGroup))

    assert ImportStatement(session_factory()).execute(
        "Checking", _two_rows(statement_df, statement_row)
    ).is_err

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(JournalEntry)) == 0
        assert session.scalar(select(func.count()).select_from(Classification)) == 0
        assert session.scalar(select(func.count()).select_from(OperationGroup)) == groups_before
