"""Migration round-trip tests against a real file database.

These drive Alembic itself rather than `base.metadata.create_all`, because the
thing under test is the migration script — the one piece of the schema that
`create_all` never executes. The downgrade path had no test at all until a
review found it broken in two ways at once.
"""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def migrated_db(tmp_path: Path) -> Iterator[tuple[Config, Path]]:
    db = tmp_path / "kohle.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    command.upgrade(config, "head")
    yield config, db


def _exec(db: Path, *statements: str) -> None:
    conn = sqlite3.connect(db)
    for statement in statements:
        conn.execute(statement)
    conn.commit()
    conn.close()


def _tables(db: Path) -> set[str]:
    conn = sqlite3.connect(db)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    return names


def test_upgrade_creates_the_ledger_tables(migrated_db) -> None:
    _, db = migrated_db
    assert {"accounts", "units", "journal_entries", "journal_lines", "prices"} <= _tables(db)
    assert "transactions" not in _tables(db)
    assert "debit_categories" not in _tables(db)


def test_downgrade_round_trips_when_every_account_fits_the_old_schema(migrated_db) -> None:
    config, db = migrated_db
    _exec(
        db,
        "INSERT INTO accounts (id, name, type, iban, parent_id, created_at) "
        "VALUES (1, 'Checking', 'asset', 'DE1', NULL, '2026-01-01')",
    )

    command.downgrade(config, "-1")
    assert "transactions" in _tables(db)
    assert "journal_lines" not in _tables(db)

    command.upgrade(config, "head")
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT name, iban FROM accounts").fetchall() == [("Checking", "DE1")]
    conn.close()


def test_downgrade_refuses_when_an_account_has_no_iban(migrated_db) -> None:
    config, db = migrated_db
    _exec(
        db,
        "INSERT INTO accounts (id, name, type, iban, parent_id, created_at) "
        "VALUES (1, 'Groceries', 'expense', NULL, NULL, '2026-01-01')",
        "INSERT INTO accounts (id, name, type, iban, parent_id, created_at) "
        "VALUES (2, 'Rent', 'expense', NULL, NULL, '2026-01-01')",
    )

    # Two IBAN-less accounts is what used to collapse to a duplicate '' and
    # kill the migration part-way through.
    with pytest.raises(RuntimeError) as exc_info:
        command.downgrade(config, "-1")
    assert "no IBAN" in str(exc_info.value)
    assert "journal_lines" in _tables(db), "refusal must leave the schema untouched"


def test_downgrade_refuses_rather_than_dropping_child_accounts(migrated_db) -> None:
    config, db = migrated_db
    _exec(
        db,
        "INSERT INTO accounts (id, name, type, iban, parent_id, created_at) "
        "VALUES (1, 'Cash', 'asset', 'DE1', NULL, '2026-01-01')",
        "INSERT INTO accounts (id, name, type, iban, parent_id, created_at) "
        "VALUES (2, 'Groceries', 'asset', 'DE2', 1, '2026-01-01')",
    )

    with pytest.raises(RuntimeError) as exc_info:
        command.downgrade(config, "-1")
    assert "parent" in str(exc_info.value)
    assert "journal_lines" in _tables(db)


def test_downgrade_refuses_rather_than_dropping_journal_entries(migrated_db) -> None:
    config, db = migrated_db
    _exec(
        db,
        "INSERT INTO accounts (id, name, type, iban, parent_id, created_at) "
        "VALUES (1, 'Checking', 'asset', 'DE1', NULL, '2026-01-01')",
        "INSERT INTO units (id, kind, identifier, name, created_at) "
        "VALUES (1, 'currency', 'EUR', 'Euro', '2026-01-01')",
        "INSERT INTO journal_entries (id, entry_date, reference, description, created_at) "
        "VALUES (1, '2026-03-01', 'ref-1', 'Aldi', '2026-01-01')",
    )

    with pytest.raises(RuntimeError) as exc_info:
        command.downgrade(config, "-1")
    assert "journal entrie" in str(exc_info.value)


def test_downgrade_refuses_rather_than_dropping_non_eur_units(migrated_db) -> None:
    config, db = migrated_db
    _exec(
        db,
        "INSERT INTO units (id, kind, identifier, name, created_at) "
        "VALUES (1, 'security', 'IE00B4L5Y983', 'Core MSCI World', '2026-01-01')",
    )

    with pytest.raises(RuntimeError) as exc_info:
        command.downgrade(config, "-1")
    assert "non-EUR unit" in str(exc_info.value)
