"""Schema lifecycle for the ledger.

Alembic is imported only inside the functions that need it: importing it costs
a noticeable fraction of every command's start-up.
"""

import os
import sqlite3
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import Connection, create_engine, pool, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from kohle.core.result import Result
from kohle.db.connection import ledger_url, make_engine, make_session_factory
from kohle.infrastructure.infra_errors import LedgerBuildFailed, LedgerError

if TYPE_CHECKING:
    from alembic.config import Config

SCRIPT_LOCATION = "kohle.db:migrations"


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


def _upgrade_to_head(staged: Path) -> str:
    from alembic import command
    from alembic.script import ScriptDirectory

    config = alembic_config()
    # NullPool and no foreign-key pragma: batch_alter_table copies and drops
    # tables, and relies on foreign keys being off.
    engine = create_engine(ledger_url(staged), poolclass=pool.NullPool)
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        engine.dispose()
    return ScriptDirectory.from_config(config).get_current_head()


def build_ledger[E](
    path: Path,
    populate: Callable[[sessionmaker[Session]], Result[Any, E]] | None,
) -> Result[str, LedgerError | E]:
    """Migrate an empty staged file to head and let `populate` write into it,
    then move it onto `path`. On any failure `path` is as it was."""
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
        head = _upgrade_to_head(staged)
        if populate is not None:
            populate_engine = make_engine(ledger_url(staged))
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
