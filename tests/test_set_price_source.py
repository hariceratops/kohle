"""Layer 2 — use case against `session`.

`SetPriceSource` and the `price_bindings` table (issue 029), design §4.2, §5.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kohle.domain.domain_errors import (
    EmptyPriceSymbol,
    NotASecurityUnit,
    UnitNotFoundError,
    UnknownPricePlugin,
)
from kohle.domain.models import OperationGroup, PriceBinding, UnitKind
from kohle.use_cases.prices import SetPriceSource
from kohle.use_cases.units import AddUnit

PLUGINS = ["alphavantage", "file"]


@pytest.fixture
def units(session: Session) -> Session:
    AddUnit(session).execute("X1", "X", UnitKind.security).unwrap()
    AddUnit(session).execute("EUR", "Euro", UnitKind.currency).unwrap()
    return session


def _bindings(session: Session) -> list[PriceBinding]:
    return list(session.scalars(select(PriceBinding)))


def _groups(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(OperationGroup)) or 0


def test_binds_a_security(units: Session) -> None:
    res = SetPriceSource(units).execute("X1", "file", "XYZ", PLUGINS)

    binding = res.unwrap()
    assert (binding.plugin_name, binding.symbol) == ("file", "XYZ")
    assert len(_bindings(units)) == 1


def test_refuses_an_unknown_unit(units: Session) -> None:
    err = SetPriceSource(units).execute("NOPE", "file", "XYZ", PLUGINS).unwrap_err()

    assert isinstance(err, UnitNotFoundError)
    assert _bindings(units) == []


def test_refuses_a_non_security_unit(units: Session) -> None:
    err = SetPriceSource(units).execute("EUR", "file", "XYZ", PLUGINS).unwrap_err()

    assert isinstance(err, NotASecurityUnit)
    assert _bindings(units) == []


def test_refuses_an_unknown_plugin_naming_the_available_ones(units: Session) -> None:
    err = SetPriceSource(units).execute("X1", "nope", "XYZ", PLUGINS).unwrap_err()

    assert isinstance(err, UnknownPricePlugin)
    assert "alphavantage, file" in str(err)
    assert _bindings(units) == []


def test_unknown_plugin_with_none_installed_says_so(units: Session) -> None:
    err = SetPriceSource(units).execute("X1", "nope", "XYZ", []).unwrap_err()

    assert "none installed" in str(err)


def test_refuses_an_empty_symbol(units: Session) -> None:
    err = SetPriceSource(units).execute("X1", "file", "  ", PLUGINS).unwrap_err()

    assert isinstance(err, EmptyPriceSymbol)


def test_rebinding_replaces_the_binding(units: Session) -> None:
    SetPriceSource(units).execute("X1", "file", "OLD", PLUGINS).unwrap()
    SetPriceSource(units).execute("X1", "alphavantage", "NEW", PLUGINS).unwrap()

    (binding,) = _bindings(units)
    assert (binding.plugin_name, binding.symbol) == ("alphavantage", "NEW")


def test_an_identical_rebind_adds_no_operation_group(units: Session) -> None:
    SetPriceSource(units).execute("X1", "file", "XYZ", PLUGINS).unwrap()
    groups = _groups(units)

    SetPriceSource(units).execute("X1", "file", "XYZ", PLUGINS).unwrap()

    assert _groups(units) == groups
    assert len(_bindings(units)) == 1
