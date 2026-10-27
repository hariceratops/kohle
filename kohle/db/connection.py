import sqlite3
from pathlib import Path
from typing import cast
from urllib.parse import quote

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from kohle.infrastructure.device_config import DeviceConfig, LedgerMode, effective

base = declarative_base()


def ledger_path(config: DeviceConfig) -> Path:
    # The registry's validator, default and KOHLE_DB all give a Path.
    return cast(Path, effective(config, "ledger.path").value)


def ledger_mode(config: DeviceConfig) -> LedgerMode:
    return cast(LedgerMode, effective(config, "ledger.mode").value)


def ledger_url(path: Path, mode: LedgerMode) -> str:
    # Neither mode creates a file, so no command can leave an empty kohle.db
    # behind; mode=ro also refuses every write. Quoted because SQLite URIs
    # give '?', '#' and '%' meaning, and an unquoted '?' in a directory name
    # silently opens a different file.
    sqlite_mode = "ro" if mode == "reader" else "rw"
    return f"sqlite:///file:{quote(str(path))}?mode={sqlite_mode}&uri=true"


def _enable_foreign_keys(dbapi_connection, _) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# A kohle write transaction is short: plugins and network calls run before it
# opens, and the ledger is a few hundred KB. 30 s outlasts any of them on a
# Raspberry Pi 3, and is short enough that a lock held by a stuck process
# surfaces while someone is still waiting on the command.
BUSY_TIMEOUT_SECONDS = 30.0


def make_engine(url: str) -> Engine:
    engine = create_engine(url, connect_args={"timeout": BUSY_TIMEOUT_SECONDS})
    event.listen(engine, "connect", _enable_foreign_keys)
    return engine


def is_busy(error: Exception) -> bool:
    # Extended codes such as SQLITE_BUSY_SNAPSHOT share the primary code's low byte.
    return (
        isinstance(error, DBAPIError)
        and isinstance(error.orig, sqlite3.Error)
        and error.orig.sqlite_errorcode & 0xFF == sqlite3.SQLITE_BUSY
    )


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
