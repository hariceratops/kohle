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


@pytest.mark.skip(reason="TODO scaffold")
def test_cost_migration_round_trip_and_refusal() -> None:
    # TODO: B
    raise NotImplementedError


@pytest.mark.skip(reason="TODO scaffold")
def test_price_unit_migration_round_trip_and_refusal() -> None:
    # TODO: C; table rebuild
    raise NotImplementedError
