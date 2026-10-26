"""The ledger file's lifecycle: opening and checking it, building and
migrating it, and copying it.

Alembic is imported only inside the functions that need it: importing it costs
a noticeable fraction of every command's start-up.
"""

import os
import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from sqlalchemy import Connection, Engine, create_engine, pool, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from kohle.core.result import Result
from kohle.db.connection import ledger_url, make_engine, make_session_factory
from kohle.infrastructure.device_config import LedgerMode
from kohle.infrastructure.infra_errors import (
    LedgerAhead,
    LedgerBehind,
    LedgerBuildFailed,
    LedgerError,
    LedgerUnreadable,
    NoLedger,
    SnapshotExists,
    SnapshotFailed,
)

if TYPE_CHECKING:
    from alembic.config import Config

SCRIPT_LOCATION = "kohle.db:migrations"

# The packaged head, so the check on every command can compare without
# importing Alembic. tests/test_schema_check.py pins it to Alembic's head; a
# stale value only sends the check down the slow path, it never misclassifies.
HEAD_REVISION = "e5a1c3b7d902"


def alembic_config() -> "Config":
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", SCRIPT_LOCATION)
    return config


def stored_revision(connection: Connection) -> str | None:
    found = connection.execute(
        text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'")
    ).first()
    if found is None:
        return None
    return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()


def _classify(path: Path, stored: str | None) -> Result[str, LedgerError]:
    if stored == HEAD_REVISION:
        return Result.ok(HEAD_REVISION)
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(alembic_config())
    head = script.get_current_head()
    if stored == head:
        return Result.ok(head)
    # History is linear, so any known revision other than head is an ancestor.
    if stored is None or stored in {s.revision for s in script.walk_revisions()}:
        return Result.err(LedgerBehind(path, stored, head))
    return Result.err(LedgerAhead(path, stored))


def check_schema(path: Path, engine: Engine) -> Result[str, LedgerError]:
    """Ok(revision) when the ledger is at the packaged head. Reads only."""
    try:
        with engine.connect() as connection:
            stored = stored_revision(connection)
    except DBAPIError as e:
        return Result.err(LedgerUnreadable(path, str(e.orig)))
    return _classify(path, stored)


def _open_checked(path: Path, mode: LedgerMode) -> Result[Engine, LedgerError]:
    """An engine on an existing, current ledger. The caller disposes of it."""
    if not path.exists():
        return Result.err(NoLedger(path, mode))
    engine = make_engine(ledger_url(path, mode))
    checked = check_schema(path, engine)
    if checked.is_err:
        engine.dispose()
        return Result.err(checked.unwrap_err())
    return Result.ok(engine)


def open_ledger(path: Path, mode: LedgerMode) -> Result[sessionmaker[Session], LedgerError]:
    return _open_checked(path, mode).map(make_session_factory)


def _upgrade_to_head(staged: Path) -> str:
    from alembic import command
    from alembic.script import ScriptDirectory

    config = alembic_config()
    # NullPool and no foreign-key pragma: batch_alter_table copies and drops
    # tables, and relies on foreign keys being off.
    engine = create_engine(ledger_url(staged, "writer"), poolclass=pool.NullPool)
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        engine.dispose()
    return ScriptDirectory.from_config(config).get_current_head()


@dataclass(frozen=True, slots=True)
class Migration:
    before: str | None
    after: str


def _copy_ledger(source: Path, staged: Path) -> None:
    # The backup API gives a consistent snapshot even with a journal present,
    # which a file copy would not.
    src = sqlite3.connect(f"file:{quote(str(source))}?mode=rw", uri=True)
    try:
        dst = sqlite3.connect(staged)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def build_ledger[E](
    path: Path,
    copy_existing: bool,
    populate: Callable[[sessionmaker[Session]], Result[Any, E]] | None,
) -> Result[str, LedgerError | E]:
    """On any failure `path` is as it was."""
    # A symlinked ledger is replaced where it lives, not turned into a file.
    target = path.resolve()
    staged: Path | None = None
    populate_engine = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Beside the target so the rename is atomic and stays on one filesystem.
        fd, name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
        os.close(fd)
        staged = Path(name)
        if copy_existing:
            _copy_ledger(target, staged)
        head = _upgrade_to_head(staged)
        if populate is not None:
            populate_engine = make_engine(ledger_url(staged, "writer"))
            populated = populate(make_session_factory(populate_engine))
            if populated.is_err:
                return Result.err(populated.unwrap_err())
        os.replace(staged, target)
        return Result.ok(head)
    except (RuntimeError, DBAPIError, sqlite3.Error, OSError) as e:
        return Result.err(LedgerBuildFailed(path, str(e)))
    finally:
        if populate_engine is not None:
            populate_engine.dispose()
        if staged is not None:
            staged.unlink(missing_ok=True)


def migrate_ledger(path: Path) -> Result[Migration, LedgerError]:
    if not path.exists():
        return Result.err(NoLedger(path, "writer"))
    # Opening read-write rolls back a hot journal, so the backup copies a clean file.
    engine = make_engine(ledger_url(path, "writer"))
    try:
        checked = check_schema(path, engine)
    finally:
        engine.dispose()
    if checked.is_ok:
        revision = checked.unwrap()
        return Result.ok(Migration(revision, revision))
    err = checked.unwrap_err()
    if not isinstance(err, LedgerBehind):
        return Result.err(err)
    built = build_ledger(path, copy_existing=True, populate=None)
    return built.map(lambda head: Migration(err.stored, head))


def snapshot_ledger(path: Path, mode: LedgerMode, dest: Path) -> Result[Path, LedgerError]:
    """Write a consistent, self-contained copy of the ledger to `dest`, which
    must not exist. Reads the ledger only."""
    opened = _open_checked(path, mode)
    if opened.is_err:
        return Result.err(opened.unwrap_err())
    engine = opened.unwrap()
    staged: Path | None = None
    try:
        # A symlink, dangling or not, is an existing path; os.replace would
        # replace the link.
        if dest.exists(follow_symlinks=False):
            return Result.err(SnapshotExists(dest))
        # Beside dest so the rename is atomic: whatever watches dest sees no
        # file or a whole snapshot, never a half-written one.
        fd, name = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".tmp")
        os.close(fd)
        staged = Path(name)
        with engine.connect() as connection:
            connection.exec_driver_sql("VACUUM INTO ?", (str(staged),))
        # VACUUM INTO does not fsync its output; without this a power cut
        # after the rename can leave a torn file at dest.
        fd = os.open(staged, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(staged, dest)
        return Result.ok(dest)
    except DBAPIError as e:
        return Result.err(SnapshotFailed(dest, str(e.orig)))
    except OSError as e:
        return Result.err(SnapshotFailed(dest, e.strerror or str(e)))
    finally:
        engine.dispose()
        if staged is not None:
            staged.unlink(missing_ok=True)
