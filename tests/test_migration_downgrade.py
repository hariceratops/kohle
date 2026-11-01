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
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from alembic import command
from kohle.db.schema import alembic_config
from kohle.domain.models import START, StateEntry

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
BEFORE_STATE_ENTRIES = "f6b2d4c8e013"
BEFORE_CAP_ENTRIES = "a7c3e9d5b124"
BEFORE_RULE_CONDITIONS = "b8d4f0a6c235"


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
        "INSERT INTO rules (id, condition, account_id, priority, created_at) "
        "VALUES (1, '{ any_field = \"REWE\" }', 2, 100, '2026-01-01')",
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
        "INSERT INTO rules (id, condition, account_id, priority, created_at) "
        "VALUES (1, '{ any_field = \"ALDI\" }', 3, 100, '2026-01-01')",
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


@pytest.fixture
def before_state_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Config, Path]:
    db = tmp_path / "kohle.db"
    db.touch()
    monkeypatch.setenv("KOHLE_DB", str(db))
    config = alembic_config()
    command.upgrade(config, BEFORE_STATE_ENTRIES)
    return config, db


def _state_entries(db: Path) -> list[tuple[str, str]]:
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT effective_from, state FROM state_entries ORDER BY effective_from").fetchall()
    conn.close()
    return rows


def test_state_setting_becomes_the_start_entry_and_leaves_settings(before_state_entries) -> None:
    config, db = before_state_entries
    _exec(db, "INSERT INTO settings (key, value) VALUES ('state', 'BY')")

    command.upgrade(config, "head")

    assert _state_entries(db) == [("0001-01-01", "BY")]
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM settings WHERE key = 'state'").fetchone() == (0,)
    conn.close()


def test_start_entry_reads_back_as_the_start_sentinel_through_the_model(before_state_entries) -> None:
    config, db = before_state_entries
    _exec(db, "INSERT INTO settings (key, value) VALUES ('state', 'BY')")
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db}")
    with Session(engine) as session:
        entry = session.query(StateEntry).one()
        assert (entry.effective_from, entry.state) == (START, "BY")
    engine.dispose()


def test_an_unset_state_creates_no_entry(before_state_entries) -> None:
    config, db = before_state_entries

    command.upgrade(config, "head")

    assert _state_entries(db) == []


def test_state_entries_round_trip_a_start_only_history(migrated_db) -> None:
    config, db = migrated_db
    _exec(db, "INSERT INTO state_entries (effective_from, state) VALUES ('0001-01-01', 'BW')")

    command.downgrade(config, BEFORE_STATE_ENTRIES)
    assert "state_entries" not in _tables(db)
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT value FROM settings WHERE key = 'state'").fetchone() == ("BW",)
    conn.close()

    command.upgrade(config, "head")
    assert _state_entries(db) == [("0001-01-01", "BW")]


def test_downgrade_refuses_rather_than_dropping_a_move(migrated_db) -> None:
    config, db = migrated_db
    _exec(
        db,
        "INSERT INTO state_entries (effective_from, state) VALUES ('0001-01-01', 'BY')",
        "INSERT INTO state_entries (effective_from, state) VALUES ('2026-01-01', 'NI')",
    )

    with pytest.raises(RuntimeError, match="state history"):
        command.downgrade(config, BEFORE_STATE_ENTRIES)
    assert "state_entries" in _tables(db), "refusal must leave the schema untouched"


def test_cap_entries_upgrade_adds_an_empty_table_and_downgrade_drops_it(migrated_db) -> None:
    config, db = migrated_db
    assert "cap_entries" in _tables(db)

    command.downgrade(config, BEFORE_CAP_ENTRIES)

    assert "cap_entries" not in _tables(db)


def test_downgrade_refuses_rather_than_dropping_caps(migrated_db) -> None:
    config, db = migrated_db
    _exec(
        db,
        "INSERT INTO accounts (id, name, type, iban, parent_id, created_at) "
        "VALUES (2, 'Groceries', 'expense', NULL, NULL, '2026-01-01')",
        "INSERT INTO cap_entries (account_id, effective_from, amount, rule) "
        "VALUES (2, '2026-01-01', 300, 'day 1')",
    )

    with pytest.raises(RuntimeError, match="spending caps"):
        command.downgrade(config, BEFORE_CAP_ENTRIES)
    assert "cap_entries" in _tables(db), "refusal must leave the schema untouched"


def test_an_end_entry_must_null_amount_and_rule_together(migrated_db) -> None:
    _, db = migrated_db
    _exec(
        db,
        "INSERT INTO accounts (id, name, type, iban, parent_id, created_at) "
        "VALUES (2, 'Groceries', 'expense', NULL, NULL, '2026-01-01')",
    )

    with pytest.raises(sqlite3.IntegrityError):
        _exec(db, "INSERT INTO cap_entries (account_id, effective_from, amount) VALUES (2, '2026-01-01', 5)")


_AWKWARD_PATTERNS = ["REWE", r"\d{4} MIETE", """it's "x" \\d""", "^DE89370400440532013000$", "tab\there"]


@pytest.fixture
def before_rule_conditions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Config, Path]:
    db = tmp_path / "kohle.db"
    db.touch()
    monkeypatch.setenv("KOHLE_DB", str(db))
    config = alembic_config()
    command.upgrade(config, BEFORE_RULE_CONDITIONS)
    return config, db


def _seed_old_rules(db: Path) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO accounts (id, name, type, iban, parent_id, created_at) "
        "VALUES (2, 'Groceries', 'expense', NULL, NULL, '2026-01-01')"
    )
    for position, pattern in enumerate(_AWKWARD_PATTERNS, start=1):
        conn.execute(
            "INSERT INTO rules (id, pattern, account_id, priority, created_at, deleted_at) "
            "VALUES (?, ?, 2, ?, '2026-01-01', ?)",
            (position, pattern, 100 + position, "2026-02-01" if position == 2 else None),
        )
    conn.execute(
        "INSERT INTO units (id, kind, identifier, name, created_at) VALUES (1, 'currency', 'EUR', 'Euro', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO journal_entries (id, entry_date, reference, description, created_at) "
        "VALUES (1, '2026-03-01', 'ref-1', 'REWE', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO classifications "
        "(id, journal_entry_id, proposed_account_id, matched_rule_id, final_account_id, corrected, created_at) "
        "VALUES (1, 1, 2, 3, 2, 0, '2026-01-01')"
    )
    conn.commit()
    conn.close()


def test_rules_become_one_any_field_condition_keeping_id_and_classification(before_rule_conditions) -> None:
    from kohle.use_cases.conditions import When, parse_stored_when

    config, db = before_rule_conditions
    _seed_old_rules(db)

    command.upgrade(config, "head")

    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT id, condition, account_id, priority, deleted_at, note FROM rules ORDER BY id").fetchall()
    matched = conn.execute("SELECT matched_rule_id FROM classifications").fetchall()
    columns = {r[1] for r in conn.execute("PRAGMA table_info(rules)")}
    conn.close()
    assert "pattern" not in columns
    assert [r[0] for r in rows] == [1, 2, 3, 4, 5]
    assert [r[2:4] for r in rows] == [(2, 101), (2, 102), (2, 103), (2, 104), (2, 105)]
    assert [r[4] is not None for r in rows] == [False, True, False, False, False]
    assert [r[5] for r in rows] == [None] * 5
    assert [parse_stored_when(r[1]).unwrap() for r in rows] == [When(any_field=p) for p in _AWKWARD_PATTERNS]
    assert matched == [(3,)]


def test_rule_conditions_round_trip_when_every_rule_is_a_plain_pattern(before_rule_conditions) -> None:
    config, db = before_rule_conditions
    _seed_old_rules(db)
    command.upgrade(config, "head")

    command.downgrade(config, BEFORE_RULE_CONDITIONS)

    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT id, pattern FROM rules ORDER BY id").fetchall()
    conn.close()
    assert rows == list(enumerate(_AWKWARD_PATTERNS, start=1))


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE rules SET note = 'x' WHERE id = 1",
        "UPDATE rules SET condition = '{ any_field = \"a\", other = \"b\" }' WHERE id = 1",
    ],
)
def test_downgrade_refuses_rather_than_dropping_a_note_or_a_richer_condition(migrated_db, statement) -> None:
    config, db = migrated_db
    _exec(
        db,
        "INSERT INTO accounts (id, name, type, iban, parent_id, created_at) "
        "VALUES (2, 'Groceries', 'expense', NULL, NULL, '2026-01-01')",
        "INSERT INTO rules (id, condition, account_id, priority, created_at) "
        "VALUES (1, '{ any_field = \"REWE\" }', 2, 100, '2026-01-01')",
        statement,
    )

    with pytest.raises(RuntimeError) as exc_info:
        command.downgrade(config, BEFORE_RULE_CONDITIONS)
    assert "classification rule" in str(exc_info.value)
    assert "condition" in {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(rules)")}


BEFORE_RERUN_RULE = "c9e1a7d35b02"


def _seed_classification(db: Path, matched: str, rerun: str) -> None:
    _exec(
        db,
        "INSERT INTO accounts (id, name, type, iban, parent_id, created_at) "
        "VALUES (2, 'Groceries', 'expense', NULL, NULL, '2026-01-01')",
        "INSERT INTO rules (id, condition, account_id, priority, created_at) "
        "VALUES (1, '{ any_field = \"REWE\" }', 2, 100, '2026-01-01')",
        "INSERT INTO journal_entries (id, entry_date, reference, description, created_at) "
        "VALUES (1, '2026-03-01', 'ref-1', 'REWE', '2026-01-01')",
        "INSERT INTO classifications "
        "(id, journal_entry_id, proposed_account_id, matched_rule_id, rerun_rule_id, final_account_id, corrected, created_at) "
        f"VALUES (1, 1, 2, {matched}, {rerun}, 2, 0, '2026-01-01')",
    )


def test_rerun_rule_column_has_its_foreign_key_and_check(migrated_db) -> None:
    _, db = migrated_db
    conn = sqlite3.connect(db)
    columns = {r[1] for r in conn.execute("PRAGMA table_info(classifications)")}
    foreign_keys = {(r[2], r[3]) for r in conn.execute("PRAGMA foreign_key_list(classifications)")}
    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'classifications'").fetchone()[0]
    conn.close()

    assert "rerun_rule_id" in columns
    assert ("rules", "rerun_rule_id") in foreign_keys
    assert "ck_classification_one_rule" in ddl
    with pytest.raises(sqlite3.IntegrityError):
        _seed_classification(db, matched="1", rerun="1")


def test_rerun_rule_round_trips_when_no_line_was_moved(migrated_db) -> None:
    config, db = migrated_db
    _seed_classification(db, matched="1", rerun="NULL")

    command.downgrade(config, BEFORE_RERUN_RULE)

    conn = sqlite3.connect(db)
    columns = {r[1] for r in conn.execute("PRAGMA table_info(classifications)")}
    rows = conn.execute("SELECT id, matched_rule_id FROM classifications").fetchall()
    conn.close()
    assert "rerun_rule_id" not in columns
    assert rows == [(1, 1)]


def test_downgrade_refuses_rather_than_dropping_a_rerun_rule(migrated_db) -> None:
    config, db = migrated_db
    _seed_classification(db, matched="NULL", rerun="1")

    with pytest.raises(RuntimeError) as exc_info:
        command.downgrade(config, BEFORE_RERUN_RULE)

    assert "moved by classify-rules" in str(exc_info.value)
    assert "rerun_rule_id" in {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(classifications)")}
