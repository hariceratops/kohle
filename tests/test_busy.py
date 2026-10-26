"""Issue 062: writers wait out a competing writer instead of failing.

TODO: one real ledger built by `run_init`; the competing process is a raw
`sqlite3` connection in a thread that sets an Event once it holds its lock."""
import pytest


def test_busy_timeout_is_set_on_engines() -> None:
    pytest.skip('TODO: PRAGMA busy_timeout reads 30000 from make_engine and from open_ledger(path, "reader")')


def test_second_writer_waits_and_succeeds() -> None:
    pytest.skip('TODO: holder BEGIN IMMEDIATE, holds 0.5 s, commits; add-account exit 0; both rows exist')


def test_timeout_at_a_statement_gives_the_locked_message() -> None:
    pytest.skip("TODO: BUSY_TIMEOUT_SECONDS patched to 0.2; exact message; no 'database is locked', no Traceback; no Cash account")


def test_timeout_at_commit_gives_the_locked_message() -> None:
    pytest.skip('TODO: holder BEGIN and read lock; exercises DbTransaction.execute')


def test_timeout_in_the_schema_check_gives_the_locked_message() -> None:
    pytest.skip('TODO: holder BEGIN EXCLUSIVE; list-accounts exit 1')


def test_is_busy_recognises_only_busy_errors() -> None:
    pytest.skip('TODO: true for busy OperationalError; false for readonly one and ValueError')
