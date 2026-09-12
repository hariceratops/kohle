from datetime import date as date_type

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from kohle.db.connection import base
from kohle.domain.models import AccountType
from kohle.use_cases.accounts import AddAccount
from kohle.use_cases.journal import PEOPLE_ROOT


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
def statement_df():
    """Build what a conformant importer plugin returns.

    The explicit `string` dtypes are the point. `read_csv` types a text column
    that is empty on every row as float64, so a statement with no counterparty
    data anywhere fails the schema check unless the plugin declares the dtype —
    see dev/design/expense-classification.md §3.3. Building the frame by hand
    in each test is where that trap hides.
    """

    def build(rows: list[dict]) -> pd.DataFrame:
        columns = ["date", "amount", "description", "counterparty_name", "counterparty_iban"]
        df = pd.DataFrame(rows, columns=columns)
        return df.astype({
            "amount": "float",
            "description": "string",
            "counterparty_name": "string",
            "counterparty_iban": "string",
        }).assign(date=lambda d: pd.to_datetime(d["date"]))

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
    ) -> dict:
        return {
            "date": day,
            "amount": amount,
            "description": description,
            "counterparty_name": counterparty_name,
            "counterparty_iban": counterparty_iban,
        }

    return build
