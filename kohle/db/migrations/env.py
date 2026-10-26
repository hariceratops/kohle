from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context
import kohle.domain.models  # noqa: F401  registers every table on base.metadata for autogenerate
from alembic.util import CommandError
from kohle.db.connection import base, ledger_mode, ledger_path, ledger_url
from kohle.infrastructure.device_config import load_device_config

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = base.metadata


def _ledger_url() -> str:
    # Alembic's own clean failure: its command line prints "FAILED: <line>"
    # and exits 1, instead of a traceback.
    loaded = load_device_config()
    if loaded.is_err:
        raise CommandError(str(loaded.unwrap_err()))
    device = loaded.unwrap()
    return ledger_url(ledger_path(device), ledger_mode(device))


def run_migrations_offline() -> None:
    # The URL only picks the dialect here.
    context.configure(
        url=_ledger_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # kohle's init and migrate pass the connection of the staged file they are
    # building. Run from the repo's `alembic` command there is none, and the
    # ledger is found the way every kohle command finds it.
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = create_engine(_ledger_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        _run(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
