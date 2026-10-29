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
from kohle.db.schema import alembic_config

# The revision each migration under test replaced. Downgrading *to* one is what
# undoes the migration above it, and unlike "-1" it keeps meaning that as newer
# revisions land on top of head.
BEFORE_MULTI_UNIT = "62313518700b"
BEFORE_COUNTERPARTY = "7f3c1d9a2b40"
BEFORE_RULES = "a1d7c4e9b208"
BEFORE_CLASSIFICATIONS = "c5b8e2f47a13"
# TODO: set to the revision each expense-splitting migration replaces, once written
# (design §10: three migrations, one per schema-bearing slice — 018, 019, 021).
BEFORE_PEOPLE_ROOT = "3e7b91c0af52"
BEFORE_SPLITS = "TODO"
BEFORE_SPLIT_GROUPS = "TODO"
BEFORE_PRICE_BINDINGS = "a1cebfe54f33"
BEFORE_PRICES_UNIQUE_PER_DAY = "b3f9d2a41c70"
BEFORE_SETTINGS = "d4e7a8c15b92"
BEFORE_SAMPLING_RULES = "e5a1c3b7d902"


@pytest.fixture
def migrated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Config, Path]]:
    db = tmp_path / "kohle.db"
    db.touch()
    monkeypatch.setenv("KOHLE_DB", str(db))
    config = alembic_config()
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
        # id 2, not 1: the People root migration seeds id 1 on every migrated_db.
        "INSERT INTO accounts (id, name, type, iban, parent_id, created_at) "
        "VALUES (2, 'Checking', 'asset', 'DE1', NULL, '2026-01-01')",
    )

    command.downgrade(config, BEFORE_MULTI_UNIT)
    assert "transactions" in _tables(db)
    assert "journal_lines" not in _tables(db)

    command.upgrade(config, "head")
    conn = sqlite3.connect(db)
    # Re-upgrading past the People-root migration re-seeds it, so "Checking"
    # is no longer the only account.
    assert conn.execute(
        "SELECT name, iban FROM accounts WHERE name = 'Checking'"
    ).fetchall() == [("Checking", "DE1")]
    conn.close()


def test_downgrade_refuses_when_an_account_has_no_iban(migrated_db) -> None:
    config, db = migrated_db
    _exec(
        db,
        "INSERT INTO accounts (id, name, type, iban, parent_id, created_at) "
        "VALUES (2, 'Groceries', 'expense', NULL, NULL, '2026-01-01')",
        "INSERT INTO accounts (id, name, type, iban, parent_id, created_at) "
        "VALUES (3, 'Rent', 'expense', NULL, NULL, '2026-01-01')",
    )

    # Two IBAN-less accounts is what used to collapse to a duplicate '' and
    # kill the migration part-way through.
    with pytest.raises(RuntimeError) as exc_info:
        command.downgrade(config, BEFORE_MULTI_UNIT)
    assert "no IBAN" in str(exc_info.value)
    assert "journal_lines" in _tables(db), "refusal must leave the schema untouched"


def test_downgrade_refuses_rather_than_dropping_child_accounts(migrated_db) -> None:
    config, db = migrated_db
    _exec(
        db,
        "INSERT INTO accounts (id, name, type, iban, parent_id, created_at) "
        "VALUES (2, 'Cash', 'asset', 'DE1', NULL, '2026-01-01')",
        "INSERT INTO accounts (id, name, type, iban, parent_id, created_at) "
        "VALUES (3, 'Groceries', 'asset', 'DE2', 2, '2026-01-01')",
    )

    with pytest.raises(RuntimeError) as exc_info:
        command.downgrade(config, BEFORE_MULTI_UNIT)
    assert "parent" in str(exc_info.value)
    assert "journal_lines" in _tables(db)


def test_downgrade_refuses_rather_than_dropping_journal_entries(migrated_db) -> None:
    config, db = migrated_db
    _exec(
        db,
        "INSERT INTO accounts (id, name, type, iban, parent_id, created_at) "
        "VALUES (2, 'Checking', 'asset', 'DE1', NULL, '2026-01-01')",
        "INSERT INTO units (id, kind, identifier, name, created_at) "
        "VALUES (1, 'currency', 'EUR', 'Euro', '2026-01-01')",
        "INSERT INTO journal_entries (id, entry_date, reference, description, created_at) "
        "VALUES (1, '2026-03-01', 'ref-1', 'Aldi', '2026-01-01')",
    )

    with pytest.raises(RuntimeError) as exc_info:
        command.downgrade(config, BEFORE_MULTI_UNIT)
    assert "journal entrie" in str(exc_info.value)


def _seed_entry(db: Path, entry_values: str) -> None:
    _exec(
        db,
        # id 2, not 1: the People root migration seeds id 1 on every migrated_db.
        "INSERT INTO accounts (id, name, type, iban, parent_id, created_at) "
        "VALUES (2, 'Checking', 'asset', 'DE1', NULL, '2026-01-01')",
        "INSERT INTO units (id, kind, identifier, name, created_at) "
        "VALUES (1, 'currency', 'EUR', 'Euro', '2026-01-01')",
        "INSERT INTO journal_entries "
        "(id, entry_date, reference, description, counterparty_name, counterparty_iban, created_at) "
        "VALUES " + entry_values,
    )


def test_counterparty_columns_round_trip_when_no_entry_carries_one(migrated_db) -> None:
    config, db = migrated_db
    _seed_entry(db, "(1, '2026-03-01', 'ref-1', 'Aldi', NULL, NULL, '2026-01-01')")

    command.downgrade(config, BEFORE_COUNTERPARTY)
    conn = sqlite3.connect(db)
    columns = {r[1] for r in conn.execute("PRAGMA table_info(journal_entries)")}
    conn.close()
    assert "counterparty_name" not in columns
    assert "counterparty_iban" not in columns

    command.upgrade(config, "head")
    conn = sqlite3.connect(db)
    assert conn.execute(
        "SELECT description, counterparty_name FROM journal_entries"
    ).fetchall() == [("Aldi", None)]
    conn.close()


def test_downgrade_refuses_rather_than_dropping_a_counterparty(migrated_db) -> None:
    config, db = migrated_db
    _seed_entry(db, "(1, '2026-03-01', 'ref-1', 'Aldi', 'ALDI SUED', NULL, '2026-01-01')")

    with pytest.raises(RuntimeError) as exc_info:
        command.downgrade(config, BEFORE_COUNTERPARTY)
    assert "counterparty" in str(exc_info.value)
    conn = sqlite3.connect(db)
    columns = {r[1] for r in conn.execute("PRAGMA table_info(journal_entries)")}
    conn.close()
    assert "counterparty_name" in columns, "refusal must leave the schema untouched"


def test_downgrade_refuses_rather_than_dropping_non_eur_units(migrated_db) -> None:
    config, db = migrated_db
    _exec(
        db,
        "INSERT INTO units (id, kind, identifier, name, created_at) "
        "VALUES (1, 'security', 'IE00B4L5Y983', 'Core MSCI World', '2026-01-01')",
    )

    with pytest.raises(RuntimeError) as exc_info:
        command.downgrade(config, BEFORE_MULTI_UNIT)
    assert "non-EUR unit" in str(exc_info.value)


def test_rules_table_round_trips_when_no_rule_exists(migrated_db) -> None:
    config, db = migrated_db
    assert "rules" in _tables(db)

    command.downgrade(config, BEFORE_RULES)
    assert "rules" not in _tables(db)

    command.upgrade(config, "head")
    assert "rules" in _tables(db)


def test_downgrade_refuses_rather_than_dropping_the_rule_set(migrated_db) -> None:
    config, db = migrated_db
    _exec(
        db,
        "INSERT INTO accounts (id, name, type, iban, parent_id, created_at) "
        "VALUES (2, 'Groceries', 'expense', NULL, NULL, '2026-01-01')",
        "INSERT INTO rules (id, pattern, account_id, priority, created_at) "
        "VALUES (1, 'REWE', 2, 100, '2026-01-01')",
    )

    with pytest.raises(RuntimeError) as exc_info:
        command.downgrade(config, BEFORE_RULES)
    assert "classification rule" in str(exc_info.value)
    assert "rules" in _tables(db), "refusal must leave the schema untouched"


def test_classifications_table_round_trips_when_nothing_is_classified(migrated_db) -> None:
    config, db = migrated_db
    assert "classifications" in _tables(db)

    command.downgrade(config, BEFORE_CLASSIFICATIONS)
    assert "classifications" not in _tables(db)

    command.upgrade(config, "head")
    assert "classifications" in _tables(db)


def test_downgrade_refuses_rather_than_dropping_classifications(migrated_db) -> None:
    config, db = migrated_db
    _seed_entry(db, "(1, '2026-03-01', 'ref-1', 'Aldi', 'ALDI SUED', NULL, '2026-01-01')")
    _exec(
        db,
        "INSERT INTO accounts (id, name, type, iban, parent_id, created_at) "
        "VALUES (3, 'Groceries', 'expense', NULL, NULL, '2026-01-01')",
        "INSERT INTO rules (id, pattern, account_id, priority, created_at) "
        "VALUES (1, 'ALDI', 3, 100, '2026-01-01')",
        "INSERT INTO classifications "
        "(id, journal_entry_id, proposed_account_id, matched_rule_id, final_account_id, "
        "corrected, created_at) "
        "VALUES (1, 1, 3, 1, 3, 0, '2026-01-01')",
    )

    # This is the labelled data the whole feature exists to accumulate, and the
    # ledger cannot reconstruct it, so the downgrade refuses rather than drops.
    with pytest.raises(RuntimeError) as exc_info:
        command.downgrade(config, BEFORE_CLASSIFICATIONS)
    assert "classification record" in str(exc_info.value)
    assert "classifications" in _tables(db), "refusal must leave the schema untouched"


def test_upgrade_seeds_the_people_root(migrated_db) -> None:
    _, db = migrated_db
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT name, type, parent_id FROM accounts WHERE name = 'People'"
    ).fetchall()
    conn.close()
    assert rows == [("People", "asset", None)]


def test_people_root_round_trips_when_the_branch_is_empty(migrated_db) -> None:
    config, db = migrated_db
    assert "People" in {r[0] for r in sqlite3.connect(db).execute("SELECT name FROM accounts")}

    command.downgrade(config, BEFORE_PEOPLE_ROOT)
    conn = sqlite3.connect(db)
    names = {r[0] for r in conn.execute("SELECT name FROM accounts")}
    conn.close()
    assert "People" not in names

    command.upgrade(config, "head")
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT name, type, parent_id FROM accounts WHERE name = 'People'").fetchall()
    conn.close()
    assert rows == [("People", "asset", None)]


def test_downgrade_refuses_rather_than_orphaning_a_person_account(migrated_db) -> None:
    config, db = migrated_db
    _exec(
        db,
        "INSERT INTO accounts (name, type, iban, parent_id, created_at) "
        "VALUES ('Alice', 'asset', NULL, (SELECT id FROM accounts WHERE name = 'People'), '2026-01-01')",
    )

    with pytest.raises(RuntimeError) as exc_info:
        command.downgrade(config, BEFORE_PEOPLE_ROOT)
    assert "1 child" in str(exc_info.value)
    assert "People" in {r[0] for r in sqlite3.connect(db).execute("SELECT name FROM accounts")}, (
        "refusal must leave the schema untouched"
    )


def test_downgrade_refuses_rather_than_dropping_lines_on_a_person_account(migrated_db) -> None:
    config, db = migrated_db
    _exec(
        db,
        "INSERT INTO accounts (name, type, iban, parent_id, created_at) "
        "VALUES ('Alice', 'asset', NULL, (SELECT id FROM accounts WHERE name = 'People'), '2026-01-01')",
        "INSERT INTO units (id, kind, identifier, name, created_at) "
        "VALUES (1, 'currency', 'EUR', 'Euro', '2026-01-01')",
        "INSERT INTO journal_entries (id, entry_date, reference, description, created_at) "
        "VALUES (1, '2026-03-01', 'ref-1', 'Dinner', '2026-01-01')",
        "INSERT INTO journal_lines "
        "(entry_id, account_id, unit_id, quantity, unit_price, is_debit, created_at) "
        "VALUES (1, (SELECT id FROM accounts WHERE name = 'Alice'), 1, 48, 1, 1, '2026-01-01')",
    )

    with pytest.raises(RuntimeError) as exc_info:
        command.downgrade(config, BEFORE_PEOPLE_ROOT)
    assert "People" in str(exc_info.value)
    assert "People" in {r[0] for r in sqlite3.connect(db).execute("SELECT name FROM accounts")}, (
        "refusal must leave the schema untouched"
    )


def test_upgrade_refuses_on_a_pre_existing_people_account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "kohle.db"
    db.touch()
    monkeypatch.setenv("KOHLE_DB", str(db))
    config = alembic_config()
    command.upgrade(config, BEFORE_PEOPLE_ROOT)
    _exec(
        db,
        "INSERT INTO accounts (name, type, iban, parent_id, created_at) "
        "VALUES ('People', 'expense', NULL, NULL, '2026-01-01')",
    )

    with pytest.raises(RuntimeError) as exc_info:
        command.upgrade(config, "head")
    assert "People" in str(exc_info.value)


def test_price_bindings_round_trips_when_empty(migrated_db) -> None:
    config, db = migrated_db
    assert "price_bindings" in _tables(db)

    command.downgrade(config, BEFORE_PRICE_BINDINGS)
    assert "price_bindings" not in _tables(db)

    command.upgrade(config, "head")
    assert "price_bindings" in _tables(db)


def test_downgrade_refuses_rather_than_dropping_a_price_binding(migrated_db) -> None:
    config, db = migrated_db
    _exec(
        db,
        "INSERT INTO units (id, kind, identifier, name, created_at) "
        "VALUES (900, 'security', 'X1', 'X', '2026-01-01')",
        "INSERT INTO price_bindings (unit_id, plugin_name, symbol) VALUES (900, 'file', 'XYZ')",
    )

    with pytest.raises(RuntimeError) as exc_info:
        command.downgrade(config, BEFORE_PRICE_BINDINGS)
    assert "1 price binding" in str(exc_info.value)
    assert "price_bindings" in _tables(db), "refusal must leave the schema untouched"


def _insert_price(db: Path, day: str, source: str) -> None:
    _exec(
        db,
        f"INSERT INTO prices (unit_id, price_date, price, source) VALUES (901, '{day}', 10, '{source}')",
    )


def test_prices_are_unique_per_unit_and_day_whatever_the_source(migrated_db) -> None:
    config, db = migrated_db
    _exec(
        db,
        "INSERT INTO units (id, kind, identifier, name, created_at) "
        "VALUES (901, 'security', 'X2', 'X', '2026-01-01')",
    )
    _insert_price(db, "2026-03-02", "file")

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        _insert_price(db, "2026-03-02", "alphavantage")

    command.downgrade(config, BEFORE_PRICES_UNIQUE_PER_DAY)
    _insert_price(db, "2026-03-02", "alphavantage")

    _exec(db, "DELETE FROM prices WHERE source = 'alphavantage'")
    command.upgrade(config, "head")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        _insert_price(db, "2026-03-02", "alphavantage")


def test_settings_round_trips_when_empty(migrated_db) -> None:
    config, db = migrated_db
    assert "settings" in _tables(db)
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM settings").fetchone() == (0,)
    conn.close()

    command.downgrade(config, BEFORE_SETTINGS)
    assert "settings" not in _tables(db)

    command.upgrade(config, "head")
    assert "settings" in _tables(db)


def test_downgrade_refuses_rather_than_dropping_a_setting(migrated_db) -> None:
    config, db = migrated_db
    _exec(db, "INSERT INTO settings (key, value) VALUES ('state', 'BW')")

    with pytest.raises(RuntimeError) as exc_info:
        command.downgrade(config, BEFORE_SETTINGS)
    assert "1 setting" in str(exc_info.value)
    assert "settings" in _tables(db), "refusal must leave the schema untouched"


_DEFAULT_RULES = "mid-month: day 15; salary: last workday"


def _rule_lists(db: Path) -> list[tuple[str]]:
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT rules FROM sampling_rule_lists ORDER BY id").fetchall()
    conn.close()
    return rows


def test_sampling_rule_lists_upgrade_seeds_the_default(migrated_db) -> None:
    _, db = migrated_db

    assert _rule_lists(db) == [(_DEFAULT_RULES,)]


def test_sampling_rule_lists_round_trips_with_only_the_default(migrated_db) -> None:
    config, db = migrated_db

    command.downgrade(config, BEFORE_SAMPLING_RULES)
    assert "sampling_rule_lists" not in _tables(db)

    command.upgrade(config, "head")
    assert _rule_lists(db) == [(_DEFAULT_RULES,)]


@pytest.mark.parametrize(
    "statements",
    [
        ["INSERT INTO sampling_rule_lists (rules) VALUES ('salary: workday 25')"],
        ["UPDATE sampling_rule_lists SET rules = 'salary: day 25'"],
    ],
    ids=["a second list", "a non-default list"],
)
def test_downgrade_refuses_rather_than_dropping_a_changed_rule_list(migrated_db, statements) -> None:
    config, db = migrated_db
    _exec(db, *statements)

    with pytest.raises(RuntimeError, match="sampling rules"):
        command.downgrade(config, BEFORE_SAMPLING_RULES)
    assert "sampling_rule_lists" in _tables(db), "refusal must leave the schema untouched"
