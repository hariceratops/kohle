"""Layer 2 — use case against `session`.

`ListPriceTargets` and `AppendPrices` (issues 030, 031), design §6.3-§6.6, §7.
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kohle.core.result import Result
from kohle.domain.domain_errors import MissingCloseResult, UnknownPricePlugin
from kohle.domain.models import (
    AccountType,
    Operation,
    OperationGroup,
    Price,
    Unit,
    UnitKind,
)
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.plugin.price_plugin import (
    Close,
    MissingEnvironmentVariable,
    PriceFetcherPlugin,
    PriceFetchError,
    PriceResult,
    Unavailable,
    UnavailableReason,
)
from kohle.services.account_services import add_account_service
from kohle.services.journal_services import LineSpec, add_journal_entry_service
from kohle.services.price_services import set_price_binding_service
from kohle.services.unit_services import add_unit_service
from kohle.use_cases.prices import (
    AlreadyStored,
    AppendPrices,
    ListPriceTargets,
    Priced,
    PriceTargets,
    Unbound,
    Unpriced,
    call_price_plugins,
)

DAY = date(2026, 3, 2)


class _FakePlugin(PriceFetcherPlugin):
    def __init__(self, name: str, result: Result[dict[str, PriceResult], PriceFetchError]) -> None:
        self._name = name
        self._result = result
        self.calls: list[list[str]] = []

    @property
    def name(self) -> str:
        return self._name

    def fetch_latest_closes(self, symbols: Sequence[str]) -> Result[dict[str, PriceResult], PriceFetchError]:
        self.calls.append(list(symbols))
        return self._result


def _close(price: str, day: date = DAY) -> Close:
    return Close(price_date=day, price=Decimal(price), currency="EUR")


@pytest.fixture
def ledger(session: Session) -> dict[str, Unit]:
    """Held: A, B (shared binding with A), C, D (unbound), plus held EUR and a held commodity."""
    ctx = DbTransactionContext(session)
    depot = add_account_service(ctx, "Depot", AccountType.asset).unwrap()
    cash = add_account_service(ctx, "Cash", AccountType.asset).unwrap()
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap()
    units = {"EUR": eur}
    for identifier, kind in [
        ("A", UnitKind.security),
        ("B", UnitKind.security),
        ("C", UnitKind.security),
        ("D", UnitKind.security),
        ("GOLD", UnitKind.commodity),
    ]:
        unit = add_unit_service(ctx, identifier, identifier, kind).unwrap()
        units[identifier] = unit
        add_journal_entry_service(
            ctx, date(2026, 1, 1), f"buy-{identifier}", identifier,
            [
                LineSpec(depot.id, unit.id, Decimal(1), Decimal(10), is_debit=True),
                LineSpec(cash.id, eur.id, Decimal(10), Decimal(1), is_debit=False),
            ],
        ).unwrap()
    for identifier, plugin, symbol in [("A", "file", "SHARED"), ("B", "file", "SHARED"), ("C", "other", "CCC")]:
        set_price_binding_service(ctx, units[identifier].id, plugin, symbol).unwrap()
    session.commit()
    return units


def _targets(session: Session) -> PriceTargets:
    return ListPriceTargets(session).execute().unwrap()


def _stored(session: Session) -> list[Price]:
    return list(session.scalars(select(Price).order_by(Price.unit_id, Price.price_date)))


def _groups(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(OperationGroup)) or 0


def _seed_price(session: Session, unit: Unit, day: date, price: str, source: str = "file") -> None:
    session.add(Price(unit_id=unit.id, price_date=day, price=Decimal(price), source=source))
    session.commit()


def test_list_price_targets_groups_by_plugin_and_symbol(session: Session, ledger: dict[str, Unit]) -> None:
    targets = _targets(session)

    assert {
        plugin: {symbol: [unit.identifier for unit in units] for symbol, units in symbols.items()}
        for plugin, symbols in targets.by_plugin.items()
    } == {"file": {"SHARED": ["A", "B"]}, "other": {"CCC": ["C"]}}
    assert [unit.identifier for unit in targets.unbound] == ["D"]


def test_every_held_security_gets_exactly_one_outcome(session: Session, ledger: dict[str, Unit]) -> None:
    _seed_price(session, ledger["C"], date(2026, 2, 27), "8")
    _seed_price(session, ledger["B"], DAY, "11")
    targets = _targets(session)
    fetched = call_price_plugins(
        targets,
        {
            "file": _FakePlugin("file", Result.ok({"SHARED": _close("12")})),
            "other": _FakePlugin(
                "other", Result.ok({"CCC": Unavailable(reason=UnavailableReason.not_covered, detail="nope")})
            ),
        },
    )

    report = AppendPrices(session).execute(targets, fetched).unwrap()

    by_unit = {outcome.unit.identifier: outcome for outcome in report.outcomes}
    assert [o.unit.identifier for o in report.outcomes] == ["A", "B", "C", "D"]
    priced = by_unit["A"]
    assert isinstance(priced, Priced)
    assert (priced.plugin_name, priced.symbol, priced.close.price, priced.close.price_date) == (
        "file", "SHARED", Decimal(12), DAY,
    )
    assert priced.previous is None
    assert isinstance(by_unit["B"], AlreadyStored)
    assert by_unit["B"].price_date == DAY
    unpriced = by_unit["C"]
    assert isinstance(unpriced, Unpriced)
    assert str(unpriced.reason) == "not_covered: nope"
    assert isinstance(by_unit["D"], Unbound)
    assert [(p.unit_id, p.price) for p in _stored(session)] == [
        (ledger["A"].id, Decimal(12)),
        (ledger["B"].id, Decimal(11)),
        (ledger["C"].id, Decimal(8)),
    ]


def test_previous_close_is_shown_alongside(session: Session, ledger: dict[str, Unit]) -> None:
    _seed_price(session, ledger["A"], date(2026, 2, 27), "9.5")
    targets = _targets(session)
    fetched = call_price_plugins(targets, {"file": _FakePlugin("file", Result.ok({"SHARED": _close("12")})),
                                           "other": _FakePlugin("other", Result.ok({}))})

    report = AppendPrices(session).execute(targets, fetched).unwrap()

    priced = next(o for o in report.outcomes if o.unit.identifier == "A")
    assert isinstance(priced, Priced)
    assert priced.previous is not None
    assert (priced.previous.price_date, priced.previous.price) == (date(2026, 2, 27), Decimal("9.5"))


def test_second_run_writes_nothing(session: Session, ledger: dict[str, Unit]) -> None:
    targets = _targets(session)
    plugins = {
        "file": _FakePlugin("file", Result.ok({"SHARED": _close("12")})),
        "other": _FakePlugin("other", Result.ok({"CCC": _close("5")})),
    }
    AppendPrices(session).execute(targets, call_price_plugins(targets, plugins)).unwrap()
    rows, groups = len(_stored(session)), _groups(session)

    report = AppendPrices(session).execute(targets, call_price_plugins(targets, plugins)).unwrap()

    assert [type(o) for o in report.outcomes] == [AlreadyStored, AlreadyStored, AlreadyStored, Unbound]
    assert len(_stored(session)) == rows == 3
    assert _groups(session) == groups


def test_plugin_err_isolated_from_other_plugins(session: Session, ledger: dict[str, Unit]) -> None:
    targets = _targets(session)
    fetched = call_price_plugins(
        targets,
        {
            "file": _FakePlugin("file", Result.err(MissingEnvironmentVariable("KOHLE_PRICE_FILE"))),
            "other": _FakePlugin("other", Result.ok({"CCC": _close("5")})),
        },
    )

    report = AppendPrices(session).execute(targets, fetched).unwrap()

    by_unit = {o.unit.identifier: o for o in report.outcomes}
    for identifier in ("A", "B"):
        outcome = by_unit[identifier]
        assert isinstance(outcome, Unpriced)
        assert str(outcome.reason) == "KOHLE_PRICE_FILE is not set"
    assert isinstance(by_unit["C"], Priced)
    assert [p.unit_id for p in _stored(session)] == [ledger["C"].id]


def test_uninstalled_plugin_leaves_its_units_unpriced(session: Session, ledger: dict[str, Unit]) -> None:
    targets = _targets(session)
    fetched = call_price_plugins(targets, {"file": _FakePlugin("file", Result.ok({"SHARED": _close("12")}))})

    report = AppendPrices(session).execute(targets, fetched).unwrap()

    outcome = next(o for o in report.outcomes if o.unit.identifier == "C")
    assert isinstance(outcome, Unpriced)
    assert isinstance(outcome.reason, UnknownPricePlugin)
    assert "Available: file" in str(outcome.reason)


def test_missing_result_is_unpriced(session: Session, ledger: dict[str, Unit]) -> None:
    targets = _targets(session)
    fetched = call_price_plugins(
        targets,
        {"file": _FakePlugin("file", Result.ok({})), "other": _FakePlugin("other", Result.ok({"CCC": _close("5")}))},
    )

    report = AppendPrices(session).execute(targets, fetched).unwrap()

    outcome = next(o for o in report.outcomes if o.unit.identifier == "A")
    assert isinstance(outcome, Unpriced)
    assert isinstance(outcome.reason, MissingCloseResult)
    assert [p.unit_id for p in _stored(session)] == [ledger["C"].id]


def test_each_plugin_is_called_once_with_only_its_own_symbols_sorted(
    session: Session, ledger: dict[str, Unit]
) -> None:
    targets = _targets(session)
    file_plugin = _FakePlugin("file", Result.ok({}))
    other_plugin = _FakePlugin("other", Result.ok({}))

    call_price_plugins(targets, {"file": file_plugin, "other": other_plugin})

    assert file_plugin.calls == [["SHARED"]]
    assert other_plugin.calls == [["CCC"]]


@pytest.mark.skip(reason="scaffold: issue 031")
def test_validation_rejections_are_per_unit() -> None:
    # TODO(031) — one test per site:
    #   - 031: zero, negative, future date, non-EUR each rejected with its own reason
    #   - another unit in the same run is still priced
    #   - an unrequested symbol lands in `ignored` and writes nothing
    raise NotImplementedError


def test_audit_trail_one_group_per_run(session: Session, ledger: dict[str, Unit]) -> None:
    targets = _targets(session)
    fetched = call_price_plugins(
        targets,
        {
            "file": _FakePlugin("file", Result.ok({"SHARED": _close("12")})),
            "other": _FakePlugin("other", Result.ok({"CCC": _close("5")})),
        },
    )
    groups_before = _groups(session)

    AppendPrices(session).execute(targets, fetched).unwrap()

    created = list(session.scalars(select(Operation).where(Operation.entity_type == "prices")))
    assert [(op.action) for op in created] == ["create"] * 3
    assert sorted(op.entity_id for op in created) == sorted(p.id for p in _stored(session))
    assert len({op.group_id for op in created}) == 1
    assert _groups(session) == groups_before + 1
