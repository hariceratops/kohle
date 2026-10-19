import os
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from click.testing import CliRunner
from sqlalchemy import create_engine, text

from kohle.app.cli.cli import cli
from kohle.db import schema
from kohle.db.schema import alembic_config

BEHIND = "d4e7a8c15b92"


def _head() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def _build(db: Path, revision: str) -> None:
    db.parent.mkdir(parents=True, exist_ok=True)
    db.touch()
    engine = create_engine(f"sqlite:///{db}")
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)
    engine.dispose()


def _query(db: Path, sql: str) -> list[tuple]:
    engine = create_engine(f"sqlite:///{db}")
    with engine.connect() as connection:
        rows = [tuple(r) for r in connection.execute(text(sql))]
    engine.dispose()
    return rows


def _revision(db: Path) -> str:
    return _query(db, "SELECT version_num FROM alembic_version")[0][0]


def _migrate():
    return CliRunner().invoke(cli, ["migrate"])


@pytest.fixture
def db() -> Path:
    return Path(os.environ["KOHLE_DB"])


def test_behind_ledger_is_upgraded_and_keeps_its_data(db: Path) -> None:
    _build(db, BEHIND)
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as connection:
        connection.execute(text("UPDATE accounts SET name = 'Kept' WHERE name = 'People'"))
    engine.dispose()

    result = _migrate()

    assert result.exit_code == 0, result.output
    assert BEHIND in result.output and _head() in result.output
    assert _revision(db) == _head()
    assert _query(db, "SELECT name FROM accounts WHERE name = 'Kept'") == [("Kept",)]
    assert _query(db, "SELECT count(*) FROM settings") == [(0,)]
    assert [p.name for p in db.parent.iterdir()] == [db.name]


def test_ledger_without_alembic_version_counts_as_behind_from_none(db: Path) -> None:
    db.parent.mkdir(parents=True)
    db.touch()

    result = _migrate()

    assert result.exit_code == 0, result.output
    assert "none" in result.output
    assert _revision(db) == _head()


def test_at_head_reports_so(db: Path) -> None:
    _build(db, "head")
    before = db.read_bytes()

    result = _migrate()

    assert result.exit_code == 0, result.output
    assert "already at revision" in result.output
    assert db.read_bytes() == before


def test_no_file_points_to_init_and_creates_nothing(db: Path) -> None:
    result = _migrate()

    assert result.exit_code == 1
    assert "kohle-cli init" in result.output
    assert not db.parent.exists()


def test_ahead_says_to_upgrade_and_leaves_file_unchanged(db: Path) -> None:
    _build(db, "head")
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'ffffffffffff'"))
    engine.dispose()
    before = db.read_bytes()

    result = _migrate()

    assert result.exit_code == 1
    assert "upgrade kohle" in result.output
    assert db.read_bytes() == before


def test_failure_leaves_ledger_bytes_and_revision_unchanged(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _build(db, BEHIND)
    before = db.read_bytes()

    def boom(staged: Path) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(schema, "_upgrade_to_head", boom)

    result = _migrate()

    assert result.exit_code == 1
    assert "boom" in result.output
    assert db.read_bytes() == before
    assert _revision(db) == BEHIND
    assert [p.name for p in db.parent.iterdir()] == [db.name]


def test_symlinked_ledger_is_upgraded_in_place_and_stays_a_link(
    db: Path, tmp_path: Path
) -> None:
    real = tmp_path / "elsewhere" / "real.db"
    _build(real, BEHIND)
    db.parent.mkdir(parents=True)
    db.symlink_to(real)

    result = _migrate()

    assert result.exit_code == 0, result.output
    assert db.is_symlink()
    assert _revision(real) == _head()
    assert [p.name for p in db.parent.iterdir()] == [db.name]


def test_migrated_ledger_is_mode_0600(db: Path) -> None:
    _build(db, BEHIND)
    db.chmod(0o644)

    assert _migrate().exit_code == 0
    assert db.stat().st_mode & 0o777 == 0o600
