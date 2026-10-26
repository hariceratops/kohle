from pathlib import Path
from typing import cast
from urllib.parse import quote

from sqlalchemy import Engine, create_engine, event
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


def make_engine(url: str) -> Engine:
    engine = create_engine(url)
    event.listen(engine, "connect", _enable_foreign_keys)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
