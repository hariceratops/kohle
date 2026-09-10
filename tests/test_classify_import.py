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
from sqlalchemy.orm import Session

from kohle.domain.domain_errors import DataframeMissingColumn
from kohle.domain.models import AccountType
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.journal import (
    ImportStatement,
    LineInput,
    QueryJournalByPeriod,
    RecordSimpleEntry,
    RecordSplitEntry,
    _optional_str,
)


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


@pytest.mark.skip(reason="scaffold: issue 015")
def test_classification_in_the_import_loop() -> None:
    # TODO(015) — one test per site:
    #   - a row matching a rule posts to that rule's target account
    #   - a row matching nothing posts to the unclassified bucket exactly as
    #     before; import with an empty rule set is unchanged behaviour
    #   - a classification row is written on both paths
    #   - posting still routes through post_entry: balance-by-value and
    #     leaf-only are not reimplemented here
    #
    # TODO(015) REGRESSION — one import produces exactly ONE OperationGroup,
    #   holding every entry and every classification. Extends
    #   test_write_creates_exactly_one_group_holding_its_operations. This is
    #   the guard against someone making the classifier a UnitOfWork, which
    #   would commit and close the session on the first row and half-commit
    #   the statement (§5.2).
    #
    # TODO(015) REGRESSION — a row failing mid-import leaves no entries, no
    #   classifications and no group. Atomicity asserted, not assumed.
    raise NotImplementedError
