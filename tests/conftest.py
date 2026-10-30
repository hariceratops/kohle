from collections.abc import Callable
from datetime import date as date_type
from decimal import Decimal
from pathlib import Path

import pytest
from click.testing import CliRunner, Result as CliResult
from sqlalchemy import create_engine, event, insert
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from kohle.app.cli.cli import cli
from kohle.db.connection import base
from kohle.domain.models import START, AccountType, SamplingRuleList, StateEntry
from kohle.plugin.importer_plugin import CashRow
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.journal import PEOPLE_ROOT


@event.listens_for(SamplingRuleList.__table__, "after_create")
def _seed_default_sampling_rules(target, connection, **kw) -> None:
    """Mirror the migration's unconditional seed: every ledger at head has a
    rule list, and tests build their schema from `base.metadata`. Fires on
    every create_all, so no test builds a schema without it (design §18.1).
    The literal is restated here as a spec value, not imported."""
    connection.execute(insert(target).values(rules="mid-month: day 15; salary: last workday"))


@pytest.fixture(autouse=True)
def _no_real_user_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test off the developer's real ledger and config files.

    A test that forgets to inject a factory gets "no ledger at ..." instead of
    touching the per-user path.
    """
    monkeypatch.setenv("KOHLE_DB", str(tmp_path / "no-ledger" / "kohle.db"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


@pytest.fixture
def write_config(tmp_path: Path):
    """Write `$XDG_CONFIG_HOME/kohle/config.toml`; return the file's path."""

    def write(content: str) -> Path:
        config = tmp_path / "xdg-config" / "kohle" / "config.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(content)
        return config

    return write


@pytest.fixture
def write_init_toml(tmp_path: Path):
    """Write `$XDG_CONFIG_HOME/kohle/init.toml`; return the file's path."""

    def write(content: str) -> Path:
        rc = tmp_path / "xdg-config" / "kohle" / "init.toml"
        rc.parent.mkdir(parents=True, exist_ok=True)
        rc.write_text(content)
        return rc

    return write


@pytest.fixture
def run_init() -> Callable[[], CliResult]:
    """Run `kohle-cli init` with no injected factory, against `KOHLE_DB`."""
    return lambda: CliRunner().invoke(cli, ["init"])


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(
        bind=engine,
        expire_on_commit=False
    )
    sess: Session = SessionLocal()
    try:
        yield sess
    finally:
        sess.close()
        base.metadata.drop_all(bind=engine)


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(
        bind=engine,
        expire_on_commit=False
    )
    base.metadata.create_all(bind=engine)
    yield SessionLocal
    base.metadata.drop_all(bind=engine)


@pytest.fixture
def start_state(session: Session) -> StateEntry:
    """Opt-in: a ledger with no `start` entry is legitimate, and its refusal
    must be testable (design §18.1)."""
    entry = StateEntry(effective_from=START, state="BY")
    session.add(entry)
    session.commit()
    return entry


@pytest.fixture
def people_root(session: Session):
    """Seed the `People` root account.

    The real migration (dev/design/expense-splitting.md §3.1, §10.1) seeds
    this row directly with an INSERT; tests build the schema from
    `base.metadata` instead of running Alembic, so the row does not exist
    unless a test asks for it. Every splitting test needs this fixture — its
    absence surfaces as an `AccountNotFoundError` from a use case that looks
    correct (design §3.2).
    """
    return AddAccount(session).execute(PEOPLE_ROOT, AccountType.asset).unwrap()


@pytest.fixture
def cash_rows():
    """Build what a conformant importer plugin returns.

    References are numbered by position ("r1", "r2", ...) unless a row names
    one, so two builds of the same list dedup against each other.
    """

    def build(rows: list[dict]) -> list[CashRow]:
        return [
            CashRow(
                entry_date=row["date"],
                reference=row.get("reference", f"r{position}"),
                description=row["description"],
                amount=Decimal(str(row["amount"])),
                counterparty_name=row["counterparty_name"],
                counterparty_iban=row["counterparty_iban"],
            )
            for position, row in enumerate(rows, start=1)
        ]

    return build


@pytest.fixture
def statement_row():
    """One statement row, with counterparty fields defaulted but overridable."""

    def build(
        day: date_type,
        amount: float,
        description: str,
        counterparty_name: str | None = None,
        counterparty_iban: str | None = None,
        reference: str | None = None,
    ) -> dict:
        row = {
            "date": day,
            "amount": amount,
            "description": description,
            "counterparty_name": counterparty_name,
            "counterparty_iban": counterparty_iban,
        }
        if reference is not None:
            row["reference"] = reference
        return row

    return build
