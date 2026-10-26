"""Issue 059: `snapshot <path>` writes a consistent copy of the ledger."""
import pytest


def test_snapshot_is_written_and_leaves_no_side_files() -> None:
    pytest.skip('TODO: exit 0; destination dir holds only the snapshot (no -journal, -wal, -shm, .tmp)')


def test_snapshot_opens_as_an_ordinary_ledger() -> None:
    pytest.skip('TODO: balance Cash and list-accounts print the same on the snapshot as on the live ledger')


def test_existing_non_empty_file_is_refused() -> None:
    pytest.skip('TODO: exit 1, SnapshotExists text, bytes unchanged')


def test_existing_empty_file_is_refused() -> None:
    pytest.skip('TODO: exit 1, SnapshotExists text, bytes unchanged')


def test_existing_directory_is_refused() -> None:
    pytest.skip('TODO: exit 1, SnapshotExists text')


def test_dangling_symlink_is_refused() -> None:
    pytest.skip('TODO: exit 1, SnapshotExists text, link untouched')


def test_live_ledger_is_untouched() -> None:
    pytest.skip('TODO: bytes, mtime and Operation/OperationGroup counts unchanged')


def test_missing_ledger_gives_the_no_ledger_line() -> None:
    pytest.skip('TODO: exit 1; neither ledger nor dest exists')


def test_ledger_behind_is_refused() -> None:
    pytest.skip('TODO: migrate line shown; dest does not exist')


def test_missing_parent_directory_fails_and_creates_nothing() -> None:
    pytest.skip('TODO: exit 1, SnapshotFailed text')


def test_failure_during_fsync_leaves_nothing() -> None:
    pytest.skip('TODO: monkeypatch os.fsync in kohle.db.schema to raise OSError; no dest, no .tmp')


def test_sqlite_specific_code_stays_in_kohle_db() -> None:
    pytest.skip('TODO: no .py outside kohle/db/ contains VACUUM, mode=ro or mode=rw')
