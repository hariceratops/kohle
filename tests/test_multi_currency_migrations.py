"""Layer 2 — the three migrations (issues 107, 111, 113). Design §9."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command

from kohle.db.schema import alembic_config

BEFORE_QUOTE_CURRENCIES = "d7f3b9a1c846"


def _columns(db: Path, table: str) -> set[str]:
    conn = sqlite3.connect(db)
    names = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    conn.close()
    return names


@pytest.fixture
def old_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, object]:
    db = tmp_path / "kohle.db"
    db.touch()
    monkeypatch.setenv("KOHLE_DB", str(db))
    config = alembic_config()
    command.upgrade(config, BEFORE_QUOTE_CURRENCIES)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO units (id, kind, identifier, name, created_at) VALUES (1, 'security', 'X1', 'X', '2026-01-01')")
    conn.execute("INSERT INTO price_bindings (unit_id, plugin_name, symbol) VALUES (1, 'file', 'X1')")
    conn.execute("INSERT INTO prices (unit_id, price_date, price, source) VALUES (1, '2026-03-02', 10, 'file')")
    conn.commit()
    conn.close()
    return db, config


def test_quote_currency_migration_round_trip_and_refusal(old_db) -> None:
    db, config = old_db

    command.upgrade(config, "a1c9e4b7d325")

    assert "quote_currency" in _columns(db, "price_bindings")
    assert "currency" in _columns(db, "prices")
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT quote_currency FROM price_bindings").fetchall() == [("EUR",)]
    assert conn.execute("SELECT currency FROM prices").fetchall() == [("EUR",)]

    command.downgrade(config, BEFORE_QUOTE_CURRENCIES)
    assert "quote_currency" not in _columns(db, "price_bindings")
    assert "currency" not in _columns(db, "prices")

    command.upgrade(config, "a1c9e4b7d325")
    conn = sqlite3.connect(db)
    conn.execute("UPDATE price_bindings SET quote_currency = 'INR'")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="Refusing to downgrade"):
        command.downgrade(config, BEFORE_QUOTE_CURRENCIES)
    assert "quote_currency" in _columns(db, "price_bindings")

    conn = sqlite3.connect(db)
    conn.execute("UPDATE price_bindings SET quote_currency = 'EUR'")
    conn.execute("UPDATE prices SET currency = 'INR'")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="Refusing to downgrade"):
        command.downgrade(config, BEFORE_QUOTE_CURRENCIES)


def test_cost_migration_round_trip_and_refusal(old_db) -> None:
    db, config = old_db
    command.upgrade(config, "a1c9e4b7d325")
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO accounts (id, name, type, created_at) VALUES (50, 'A', 'asset', '2026-01-01')")
    conn.execute("INSERT INTO journal_entries (id, entry_date, reference, description, created_at) VALUES (1, '2026-03-01', 'r', 'd', '2026-01-01')")
    conn.execute(
        "INSERT INTO journal_lines (id, entry_id, account_id, unit_id, quantity, unit_price, is_debit, created_at) "
        "VALUES (1, 1, 50, 1, 10, 1, 1, '2026-01-01')"
    )
    conn.commit()
    conn.close()

    command.upgrade(config, "b4d8f1c6e920")
    assert "cost" in _columns(db, "journal_lines")
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT cost FROM journal_lines").fetchall() == [(None,)]

    command.downgrade(config, "a1c9e4b7d325")
    assert "cost" not in _columns(db, "journal_lines")

    command.upgrade(config, "b4d8f1c6e920")
    conn = sqlite3.connect(db)
    conn.execute("UPDATE journal_lines SET cost = 10")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="Refusing to downgrade"):
        command.downgrade(config, "a1c9e4b7d325")
    assert "cost" in _columns(db, "journal_lines")


def test_price_unit_migration_round_trip_and_refusal(old_db) -> None:
    db, config = old_db
    command.upgrade(config, "b4d8f1c6e920")
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO accounts (id, name, type, created_at) VALUES (50, 'A', 'asset', '2026-01-01')")
    conn.execute("INSERT INTO journal_entries (id, entry_date, reference, description, created_at) VALUES (1, '2026-03-01', 'r', 'd', '2026-01-01')")
    conn.execute(
        "INSERT INTO journal_lines (id, entry_id, account_id, unit_id, quantity, unit_price, is_debit, created_at) "
        "VALUES (1, 1, 50, 1, 10, 1, 1, '2026-01-01')"
    )
    conn.commit()
    conn.close()

    command.upgrade(config, "c7e2a9d4b185")
    assert "price_unit_id" in _columns(db, "journal_lines")
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT id, quantity, price_unit_id FROM journal_lines").fetchall() == [(1, 10, None)]
    table = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'journal_lines'").fetchone()[0]
    assert "uq_journal_line_entry_account_unit_side" in table
    assert "fk_journal_lines_price_unit_id_units" in table
    conn.close()

    command.downgrade(config, "b4d8f1c6e920")
    assert "price_unit_id" not in _columns(db, "journal_lines")
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT id, cost FROM journal_lines").fetchall() == [(1, None)]
    conn.close()

    command.upgrade(config, "c7e2a9d4b185")
    conn = sqlite3.connect(db)
    conn.execute("UPDATE journal_lines SET price_unit_id = 1")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="Refusing to downgrade"):
        command.downgrade(config, "b4d8f1c6e920")
    assert "price_unit_id" in _columns(db, "journal_lines")
