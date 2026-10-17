"""Layer 2 — use case against `session`.

`latest_close` (issue 032), design §8.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from kohle.domain.models import Price, UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.unit_services import add_unit_service
from kohle.use_cases.prices import Fresh, NoClose, Stale, latest_close

TODAY = date(2026, 3, 10)


@pytest.fixture
def unit_id(session: Session) -> int:
    unit = add_unit_service(DbTransactionContext(session), "A", "A", UnitKind.security).unwrap()
    session.commit()
    return unit.id


def _seed(session: Session, unit_id: int, age_days: int, price: str = "10", source: str = "file") -> None:
    session.add(
        Price(unit_id=unit_id, price_date=TODAY - timedelta(days=age_days), price=Decimal(price), source=source)
    )
    session.commit()


def test_fresh_stale_and_none(session: Session, unit_id: int) -> None:
    ctx = DbTransactionContext(session)

    none = latest_close(ctx, unit_id, TODAY).unwrap()
    assert none == NoClose()

    _seed(session, unit_id, 30, "9", "old")
    stale = latest_close(ctx, unit_id, TODAY).unwrap()
    assert isinstance(stale, Stale)
    assert stale.close.price == Decimal(9)
    assert stale.close.source == "old"
    assert stale.close.price_date == TODAY - timedelta(days=30)
    assert stale != none

    _seed(session, unit_id, 1, "11", "new")
    fresh = latest_close(ctx, unit_id, TODAY).unwrap()
    assert isinstance(fresh, Fresh)
    assert fresh.close.price == Decimal(11)
    assert fresh.close.source == "new"


def test_boundary_day_is_pinned(session: Session, unit_id: int) -> None:
    ctx = DbTransactionContext(session)
    _seed(session, unit_id, 7)
    assert isinstance(latest_close(ctx, unit_id, TODAY).unwrap(), Fresh)
    assert isinstance(latest_close(ctx, unit_id, TODAY + timedelta(days=1)).unwrap(), Stale)

    assert isinstance(latest_close(ctx, unit_id, TODAY, max_age_days=7).unwrap(), Fresh)
    assert isinstance(latest_close(ctx, unit_id, TODAY, max_age_days=6).unwrap(), Stale)

    _seed(session, unit_id, 1, "12")
    assert isinstance(latest_close(ctx, unit_id, TODAY, max_age_days=1).unwrap(), Fresh)
    assert isinstance(latest_close(ctx, unit_id, TODAY + timedelta(days=1), max_age_days=1).unwrap(), Stale)


def test_a_close_after_as_of_is_never_used(session: Session, unit_id: int) -> None:
    ctx = DbTransactionContext(session)
    _seed(session, unit_id, 10, "9")
    _seed(session, unit_id, -5, "99")

    close = latest_close(ctx, unit_id, TODAY, 7).unwrap()

    assert isinstance(close, Stale)
    assert close.close.price == Decimal(9)


def test_as_of_before_the_first_close_is_no_close(session: Session, unit_id: int) -> None:
    _seed(session, unit_id, 0, "9")

    assert latest_close(DbTransactionContext(session), unit_id, TODAY - timedelta(days=1)).unwrap() == NoClose()
