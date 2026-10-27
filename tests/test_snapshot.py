"""Issue 059: `snapshot <path>` writes a consistent copy of the ledger."""

import os
from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine, text

from kohle.app.cli.cli import cli
from kohle.db import schema
from tests.test_migrate import BEHIND, _build

MISSING_PARENT_REASON = "No such file or directory"


def _invoke(*args: str):
    return CliRunner().invoke(cli, list(args))


@pytest.fixture
def live(write_init_rc, run_init) -> Path:
    write_init_rc('state = "BW"\n')
    db = Path(os.environ["KOHLE_DB"])
    assert run_init().exit_code == 0
    for args in (
        ["add-account", "Checking", "--type", "asset"],
        ["add-account", "Groceries"],
        ["add-unit", "IE00B4L5Y983", "Core MSCI World"],
        ["record", "2026-03-01", "Aldi", "80", "--from", "Checking", "--to", "Groceries"],
    ):
        result = _invoke(*args)
        assert result.exit_code == 0, result.output
    return db


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    out.mkdir()
    return out / "copy.db"


def _counts(db: Path) -> tuple[int, int]:
    engine = create_engine(f"sqlite:///{db}")
    try:
        with engine.connect() as connection:
            ops = connection.execute(text("SELECT count(*) FROM operations")).scalar_one()
            groups = connection.execute(text("SELECT count(*) FROM operation_groups")).scalar_one()
    finally:
        engine.dispose()
    return ops, groups


def test_snapshot_is_written_and_leaves_no_side_files(live: Path, dest: Path) -> None:
    result = _invoke("snapshot", str(dest))

    assert result.exit_code == 0, result.output
    assert [p.name for p in dest.parent.iterdir()] == [dest.name]


def test_snapshot_opens_as_an_ordinary_ledger(live: Path, dest: Path, monkeypatch) -> None:
    live_balance = _invoke("balance", "Checking")
    live_accounts = _invoke("list-accounts")
    assert _invoke("snapshot", str(dest)).exit_code == 0

    monkeypatch.setenv("KOHLE_DB", str(dest))
    balance = _invoke("balance", "Checking")
    accounts = _invoke("list-accounts")

    assert balance.exit_code == 0, balance.output
    assert balance.output == live_balance.output
    assert accounts.exit_code == 0, accounts.output
    assert accounts.output == live_accounts.output


def _refused(dest: Path) -> None:
    result = _invoke("snapshot", str(dest))
    assert result.exit_code == 1
    assert f"{dest} already exists; snapshot never overwrites a file" in result.output


def test_existing_non_empty_file_is_refused(live: Path, dest: Path) -> None:
    dest.write_bytes(b"keep me")

    _refused(dest)

    assert dest.read_bytes() == b"keep me"


def test_existing_empty_file_is_refused(live: Path, dest: Path) -> None:
    dest.touch()

    _refused(dest)

    assert dest.read_bytes() == b""
    assert [p.name for p in dest.parent.iterdir()] == [dest.name]


def test_existing_directory_is_refused(live: Path, dest: Path) -> None:
    dest.mkdir()

    _refused(dest)

    assert dest.is_dir() and list(dest.iterdir()) == []


def test_dangling_symlink_is_refused(live: Path, dest: Path) -> None:
    target = dest.parent / "nowhere"
    dest.symlink_to(target)

    _refused(dest)

    assert dest.is_symlink() and os.readlink(dest) == str(target)
    assert not target.exists()


def test_live_ledger_is_untouched(live: Path, dest: Path) -> None:
    before_bytes = live.read_bytes()
    before_mtime = live.stat().st_mtime_ns
    before_counts = _counts(live)

    assert _invoke("snapshot", str(dest)).exit_code == 0

    assert live.read_bytes() == before_bytes
    assert live.stat().st_mtime_ns == before_mtime
    assert _counts(live) == before_counts


def test_missing_ledger_gives_the_no_ledger_line(dest: Path) -> None:
    db = Path(os.environ["KOHLE_DB"])

    result = _invoke("snapshot", str(dest))

    assert result.exit_code == 1
    assert f"no ledger at {db}; run `kohle-cli init`" in result.output
    assert not db.exists() and not dest.exists()


def test_ledger_behind_is_refused() -> None:
    db = Path(os.environ["KOHLE_DB"])
    _build(db, BEHIND)
    out = db.parent / "copy.db"

    result = _invoke("snapshot", str(out))

    assert result.exit_code == 1
    assert "kohle-cli migrate" in result.output
    assert not out.exists()


def test_missing_parent_directory_fails_and_creates_nothing(live: Path, tmp_path: Path) -> None:
    out = tmp_path / "absent" / "copy.db"

    result = _invoke("snapshot", str(out))

    assert result.exit_code == 1
    assert f"writing a snapshot to {out} failed: {MISSING_PARENT_REASON}" in result.output
    assert not out.parent.exists()


def test_failure_during_fsync_leaves_nothing(live: Path, dest: Path, monkeypatch) -> None:
    def boom(_fd: int) -> None:
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(schema.os, "fsync", boom)

    result = _invoke("snapshot", str(dest))

    assert result.exit_code == 1
    assert "writing a snapshot to" in result.output
    assert list(dest.parent.iterdir()) == []


def test_sqlite_specific_code_stays_in_kohle_db() -> None:
    root = Path(schema.__file__).resolve().parents[1]
    offenders = [
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if "db" not in p.relative_to(root).parts[:1]
        and any(token in p.read_text() for token in ("VACUUM", "mode=ro", "mode=rw"))
    ]
    assert offenders == []
