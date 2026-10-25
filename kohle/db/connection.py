from pathlib import Path
from typing import cast
from urllib.parse import quote

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from kohle.infrastructure.device_config import DeviceConfig, effective

base = declarative_base()


def ledger_path(config: DeviceConfig) -> Path:
    # The registry's validator, default and KOHLE_DB all give a Path.
    return cast(Path, effective(config, "ledger.path").value)


def ledger_url(path: Path) -> str:
    # mode=rw opens an existing file read-write and never creates one, so no
    # command can leave an empty kohle.db behind. Quoted because SQLite URIs
    # give '?', '#' and '%' meaning, and an unquoted '?' in a directory name
    # silently opens a different file.
    return f"sqlite:///file:{quote(str(path))}?mode=rw&uri=true"


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
