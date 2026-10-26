"""Issue 062: writers wait out a competing writer instead of failing."""

import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from click.testing import CliRunner
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from kohle.app.cli.cli import cli
from kohle.db import connection
from kohle.db.connection import is_busy, ledger_url, make_engine
from kohle.db.schema import open_ledger

LOCKED = "Error: the ledger stayed locked by another process; nothing was changed, try again\n"

INSERT_ACCOUNT = "INSERT INTO accounts (name, type, created_at) VALUES ('Held', 'asset', '2026-03-01')"


@pytest.fixture
def ledger(write_init_rc, run_init) -> Path:
    write_init_rc('state = "BW"\n')
    assert run_init().exit_code == 0
    return Path(os.environ["KOHLE_DB"])


@contextmanager
def _holding(path: Path, statements: list[str], seconds: float) -> Iterator[None]:
    """A competing process: runs `statements`, keeps its lock for `seconds`, then commits."""
    locked = threading.Event()

    def hold() -> None:
        conn = sqlite3.connect(path, isolation_level=None)
        try:
            for statement in statements:
                conn.execute(statement).fetchall()
            locked.set()
            time.sleep(seconds)
            conn.execute("COMMIT")
        finally:
            locked.set()
            conn.close()

    thread = threading.Thread(target=hold)
    thread.start()
    assert locked.wait(5)
    try:
        yield
    finally:
        thread.join()


def _accounts(path: Path) -> set[str]:
    with sqlite3.connect(path) as conn:
        return {name for (name,) in conn.execute("SELECT name FROM accounts")}


def _add_cash():
    return CliRunner().invoke(cli, ["add-account", "Cash"])


def test_busy_timeout_is_set_on_engines(ledger: Path) -> None:
    for engine in (make_engine(ledger_url(ledger, "writer")), open_ledger(ledger, "reader").unwrap().kw["bind"]):
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA busy_timeout")).scalar_one() == 30000
        engine.dispose()


def test_second_writer_waits_and_succeeds(ledger: Path) -> None:
    with _holding(ledger, ["BEGIN IMMEDIATE", INSERT_ACCOUNT], 0.5):
        result = _add_cash()
    assert result.exit_code == 0, result.output
    assert {"Held", "Cash"} <= _accounts(ledger)


def test_timeout_at_a_statement_gives_the_locked_message(ledger: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connection, "BUSY_TIMEOUT_SECONDS", 0.2)
    with _holding(ledger, ["BEGIN IMMEDIATE", INSERT_ACCOUNT], 1.5):
        result = _add_cash()
    assert result.exit_code == 1
    assert result.output == LOCKED
    assert "database is locked" not in result.output
    assert "Traceback" not in result.output
    assert "Held" in _accounts(ledger)
    assert "Cash" not in _accounts(ledger)


def test_timeout_at_commit_gives_the_locked_message(ledger: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connection, "BUSY_TIMEOUT_SECONDS", 0.2)
    with _holding(ledger, ["BEGIN", "SELECT count(*) FROM accounts"], 1.5):
        result = _add_cash()
    assert result.exit_code == 1
    assert result.output == LOCKED
    assert "Cash" not in _accounts(ledger)


def test_timeout_in_the_schema_check_gives_the_locked_message(ledger: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connection, "BUSY_TIMEOUT_SECONDS", 0.2)
    with _holding(ledger, ["BEGIN EXCLUSIVE"], 1.5):
        result = CliRunner().invoke(cli, ["list-accounts"])
    assert result.exit_code == 1
    assert result.output == LOCKED


def test_is_busy_recognises_only_busy_errors(ledger: Path) -> None:
    engine = make_engine(ledger_url(ledger, "writer"))
    holder = sqlite3.connect(ledger, isolation_level=None)
    holder.execute("BEGIN EXCLUSIVE")
    busy_engine = make_engine(ledger_url(ledger, "writer"))
    try:
        with busy_engine.connect() as conn:
            conn.connection.driver_connection.execute("PRAGMA busy_timeout=0")  # type: ignore[union-attr]
            with pytest.raises(OperationalError) as busy:
                conn.execute(text("SELECT count(*) FROM accounts"))
    finally:
        holder.execute("ROLLBACK")
        holder.close()
        busy_engine.dispose()
    assert is_busy(busy.value)

    with open_ledger(ledger, "reader").unwrap()() as session:
        with pytest.raises(OperationalError) as readonly:
            session.execute(text(INSERT_ACCOUNT))
    assert "readonly" in str(readonly.value)
    assert not is_busy(readonly.value)
    assert not is_busy(ValueError("x"))
    engine.dispose()
