"""Migrations for the transfer and remittance columns (issues 126, 132, 135). Design §18.8."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command

from kohle.db.schema import HEAD_REVISION, alembic_config

BEFORE_TRANSFER_RULES = "c7e2a9d4b185"
TRANSFER_RULES = "e8b3c5a1d704"
REMITTANCE_RULES = "f2a6d8c4e195"
ENTRY_REVERSALS = "a9d3c7e1b406"


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
    command.upgrade(config, BEFORE_TRANSFER_RULES)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO accounts (id, name, type, created_at) VALUES (10, 'Checking', 'asset', '2026-01-01')")
    conn.execute("INSERT INTO accounts (id, name, type, created_at) VALUES (11, 'Savings', 'asset', '2026-01-01')")
    conn.execute(
        "INSERT INTO rules (id, condition, account_id, priority, created_at) "
        "VALUES (1, 'description = \"x\"', 11, 100, '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO journal_entries (id, entry_date, reference, description, created_at) "
        "VALUES (1, '2026-04-03', 'r1', 'x', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO journal_entries (id, entry_date, reference, description, created_at) "
        "VALUES (2, '2026-04-04', 'r2', 'x', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO classifications (id, journal_entry_id, proposed_account_id, final_account_id, corrected, created_at) "
        "VALUES (1, 1, 11, 11, 0, '2026-01-01')"
    )
    conn.commit()
    conn.close()
    return db, config


def test_head_is_pinned() -> None:
    assert HEAD_REVISION == ENTRY_REVERSALS


def test_existing_rows_come_out_as_categories_and_the_columns_round_trip(old_db) -> None:
    db, config = old_db

    command.upgrade(config, TRANSFER_RULES)

    assert "kind" in _columns(db, "rules")
    assert {"kind", "mirror_of_entry_id"} <= _columns(db, "classifications")
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT kind FROM rules").fetchall() == [("category",)]
    assert conn.execute("SELECT kind, mirror_of_entry_id FROM classifications").fetchall() == [("category", None)]
    conn.close()

    command.downgrade(config, BEFORE_TRANSFER_RULES)

    assert "kind" not in _columns(db, "rules")
    assert not {"kind", "mirror_of_entry_id"} & _columns(db, "classifications")


@pytest.mark.parametrize(
    "offending",
    [
        "UPDATE rules SET kind = 'transfer'",
        "UPDATE classifications SET kind = 'transfer'",
        "UPDATE classifications SET kind = 'mirror', mirror_of_entry_id = 2",
    ],
)
def test_downgrade_refuses_a_transfer_and_leaves_the_schema_untouched(old_db, offending: str) -> None:
    db, config = old_db
    command.upgrade(config, TRANSFER_RULES)
    conn = sqlite3.connect(db)
    conn.execute(offending)
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="Refusing to downgrade"):
        command.downgrade(config, BEFORE_TRANSFER_RULES)

    assert "kind" in _columns(db, "rules")
    assert "mirror_of_entry_id" in _columns(db, "classifications")


def test_the_checks_reject_a_mirror_without_its_transfer_and_a_second_mirror_of_one_transfer(old_db) -> None:
    db, config = old_db
    command.upgrade(config, TRANSFER_RULES)
    conn = sqlite3.connect(db)

    with pytest.raises(sqlite3.IntegrityError, match="ck_classification_mirror"):
        conn.execute("UPDATE classifications SET kind = 'mirror'")
    with pytest.raises(sqlite3.IntegrityError, match="ck_classification_mirror"):
        conn.execute("UPDATE classifications SET mirror_of_entry_id = 2")

    conn.execute(
        "INSERT INTO classifications (id, journal_entry_id, proposed_account_id, final_account_id, corrected, "
        "kind, mirror_of_entry_id, created_at) VALUES (2, 2, 11, 10, 0, 'mirror', 1, '2026-01-01')"
    )
    conn.execute("INSERT INTO journal_entries (id, entry_date, reference, description, created_at) VALUES (3, '2026-04-05', 'r3', 'x', '2026-01-01')")
    with pytest.raises(sqlite3.IntegrityError, match="uq_classification_mirror_of|UNIQUE"):
        conn.execute(
            "INSERT INTO classifications (id, journal_entry_id, proposed_account_id, final_account_id, corrected, "
            "kind, mirror_of_entry_id, created_at) VALUES (3, 3, 11, 10, 0, 'mirror', 1, '2026-01-01')"
        )
    conn.close()


@pytest.fixture
def transfer_db(old_db) -> tuple[Path, object]:
    db, config = old_db
    command.upgrade(config, TRANSFER_RULES)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO accounts (id, name, type, created_at) VALUES (12, 'IndianBank', 'asset', '2026-01-01')")
    conn.execute("INSERT INTO units (id, identifier, name, kind, created_at) VALUES (1, 'INR', 'Rupee', 'currency', '2026-01-01')")
    conn.commit()
    conn.close()
    return db, config


def test_the_remittance_columns_round_trip_when_unused(transfer_db) -> None:
    db, config = transfer_db

    command.upgrade(config, REMITTANCE_RULES)

    assert "unit_id" in _columns(db, "rules")
    assert {"remittance_account_id", "remittance_unit_id", "completion_entry_id"} <= _columns(db, "classifications")
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT kind, unit_id FROM rules").fetchall() == [("category", None)]
    conn.close()

    command.downgrade(config, TRANSFER_RULES)

    assert "unit_id" not in _columns(db, "rules")
    assert not {"remittance_account_id", "remittance_unit_id", "completion_entry_id"} & _columns(db, "classifications")


@pytest.mark.parametrize(
    "offending",
    [
        "UPDATE rules SET kind = 'remittance', unit_id = 1, account_id = 12",
        "UPDATE classifications SET kind = 'remittance', remittance_account_id = 12, remittance_unit_id = 1",
        "UPDATE classifications SET kind = 'remittance', remittance_account_id = 12, remittance_unit_id = 1, "
        "completion_entry_id = 2",
    ],
)
def test_downgrade_refuses_a_remittance_and_leaves_the_schema_untouched(transfer_db, offending: str) -> None:
    db, config = transfer_db
    command.upgrade(config, REMITTANCE_RULES)
    conn = sqlite3.connect(db)
    conn.execute(offending)
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="Refusing to downgrade"):
        command.downgrade(config, TRANSFER_RULES)

    assert "unit_id" in _columns(db, "rules")
    assert "completion_entry_id" in _columns(db, "classifications")


@pytest.mark.parametrize(
    ("statement", "check"),
    [
        ("UPDATE rules SET kind = 'remittance'", "ck_rule_remittance_unit"),
        ("UPDATE rules SET unit_id = 1", "ck_rule_remittance_unit"),
        ("UPDATE classifications SET kind = 'remittance'", "ck_classification_remittance"),
        ("UPDATE classifications SET remittance_account_id = 12", "ck_classification_remittance"),
        (
            "UPDATE classifications SET kind = 'remittance', remittance_account_id = 12",
            "ck_classification_remittance",
        ),
        ("UPDATE classifications SET completion_entry_id = 2", "ck_classification_completion"),
    ],
)
def test_the_checks_reject_a_remittance_without_its_unit_and_a_stray_completion(
    transfer_db, statement: str, check: str
) -> None:
    db, config = transfer_db
    command.upgrade(config, REMITTANCE_RULES)
    conn = sqlite3.connect(db)

    with pytest.raises(sqlite3.IntegrityError, match=check):
        conn.execute(statement)
    conn.close()


def test_the_reversal_column_round_trips_when_no_entry_reverses_another(transfer_db) -> None:
    db, config = transfer_db

    command.upgrade(config, ENTRY_REVERSALS)
    assert "reverses_entry_id" in _columns(db, "journal_entries")
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT reverses_entry_id FROM journal_entries").fetchall() == [(None,), (None,)]
    conn.close()

    command.downgrade(config, REMITTANCE_RULES)

    assert "reverses_entry_id" not in _columns(db, "journal_entries")


def test_downgrade_refuses_a_reversal_and_leaves_the_schema_untouched(transfer_db) -> None:
    db, config = transfer_db
    command.upgrade(config, ENTRY_REVERSALS)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE journal_entries SET reverses_entry_id = 1 WHERE id = 2")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="Refusing to downgrade"):
        command.downgrade(config, REMITTANCE_RULES)

    assert "reverses_entry_id" in _columns(db, "journal_entries")


def test_a_second_reversal_of_the_same_entry_is_rejected(transfer_db) -> None:
    db, config = transfer_db
    command.upgrade(config, ENTRY_REVERSALS)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO journal_entries (id, entry_date, reference, description, created_at, reverses_entry_id) "
        "VALUES (3, '2026-04-04', 'r3', 'x', '2026-01-01', 1)"
    )

    with pytest.raises(sqlite3.IntegrityError, match="reverses_entry_id"):
        conn.execute(
            "INSERT INTO journal_entries (id, entry_date, reference, description, created_at, reverses_entry_id) "
            "VALUES (4, '2026-04-04', 'r4', 'x', '2026-01-01', 1)"
        )
    conn.close()
