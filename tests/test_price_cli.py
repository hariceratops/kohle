"""Layer 3 — CLI through `CliRunner`.

`set-price-source` and `fetch-prices` (issues 029-033), design §5, §6.7, §15. `kohle.app.cli.cli.load_price_plugins` monkeypatched, as in the importer CLI tests.
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from click.testing import CliRunner
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from kohle.app.cli.cli import cli
from kohle.app.plugins.kohle_alphavantage_price_fetcher import AlphaVantagePriceFetcher
from kohle.app.plugins.kohle_file_price_fetcher import FilePriceFetcher
from kohle.core.result import Result
from kohle.domain.models import (
    AccountType,
    OperationGroup,
    Price,
    PriceBinding,
    UnitKind,
)
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.plugin.price_plugin import PriceFetcherPlugin, PriceFetchError, PriceResult
from kohle.services.account_services import add_account_service
from kohle.services.journal_services import LineSpec, add_journal_entry_service
from kohle.services.unit_services import get_unit_by_identifier_service
from kohle.use_cases.units import AddUnit


class _FakeFetcher(PriceFetcherPlugin):
    @property
    def name(self) -> str:
        return "fake"

    def fetch_latest_closes(
        self, symbols: Sequence[str]
    ) -> Result[dict[str, PriceResult], PriceFetchError]:
        return Result.ok({})


@pytest.fixture
def ledger(session_factory: sessionmaker) -> sessionmaker:
    with session_factory() as session:
        AddUnit(session).execute("X1", "X", UnitKind.security).unwrap()
        AddUnit(session).execute("EUR", "Euro", UnitKind.currency).unwrap()
    return session_factory


def _set_price_source(ledger: sessionmaker, monkeypatch: pytest.MonkeyPatch, *args: str):
    monkeypatch.setattr("kohle.app.cli.cli.load_price_plugins", lambda: {"fake": _FakeFetcher()})
    return CliRunner().invoke(cli, ["set-price-source", *args], obj=ledger)


def test_set_price_source_success(ledger: sessionmaker, monkeypatch: pytest.MonkeyPatch) -> None:
    result = _set_price_source(ledger, monkeypatch, "X1", "fake", "XYZ")

    assert result.exit_code == 0, result.output
    assert "Price source for X1: fake XYZ" in result.output
    with ledger() as session:
        (binding,) = session.scalars(select(PriceBinding))
        assert (binding.plugin_name, binding.symbol) == ("fake", "XYZ")


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("NOPE", "fake", "XYZ"), "Unit NOPE not found"),
        (("EUR", "fake", "XYZ"), "is a currency, not a security"),
        (("X1", "other", "XYZ"), "Available: fake"),
        (("X1", "fake", " "), "symbol cannot be empty"),
    ],
)
def test_set_price_source_refusals_exit_non_zero(
    ledger: sessionmaker, monkeypatch: pytest.MonkeyPatch, args: tuple[str, ...], message: str
) -> None:
    result = _set_price_source(ledger, monkeypatch, *args)

    assert result.exit_code != 0
    assert message in result.output
    with ledger() as session:
        assert session.scalars(select(PriceBinding)).all() == []


def _hold(session_factory: sessionmaker, *identifiers: str) -> None:
    with session_factory() as session:
        ctx = DbTransactionContext(session)
        depot = add_account_service(ctx, "Depot", AccountType.asset).unwrap()
        cash = add_account_service(ctx, "Cash", AccountType.asset).unwrap()
        eur = get_unit_by_identifier_service(ctx, "EUR").unwrap()
        for identifier in identifiers:
            unit = get_unit_by_identifier_service(ctx, identifier).unwrap()
            add_journal_entry_service(
                ctx, date(2026, 1, 1), f"buy-{identifier}", identifier,
                [
                    LineSpec(depot.id, unit.id, Decimal(1), Decimal(10), is_debit=True),
                    LineSpec(cash.id, eur.id, Decimal(10), Decimal(1), is_debit=False),
                ],
            ).unwrap()
        session.commit()


def _fetch_prices(ledger: sessionmaker, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("kohle.app.cli.cli.load_price_plugins", lambda: {"file": FilePriceFetcher()})
    return CliRunner().invoke(cli, ["fetch-prices"], obj=ledger)


def _bind(ledger: sessionmaker, monkeypatch: pytest.MonkeyPatch, unit: str, symbol: str) -> None:
    monkeypatch.setattr("kohle.app.cli.cli.load_price_plugins", lambda: {"file": FilePriceFetcher()})
    result = CliRunner().invoke(cli, ["set-price-source", unit, "file", symbol], obj=ledger)
    assert result.exit_code == 0, result.output


def test_fetch_prices_with_the_file_plugin(
    ledger: sessionmaker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with ledger() as session:
        AddUnit(session).execute("X2", "Y", UnitKind.security).unwrap()
    _hold(ledger, "X1", "X2")
    _bind(ledger, monkeypatch, "X1", "XYZ")
    _bind(ledger, monkeypatch, "X2", "ABC")
    price_file = tmp_path / "prices.csv"
    price_file.write_text("identifier,date,close\nXYZ,2026-03-02,12.5\nABC,2026-03-02,3\n", encoding="utf-8")
    monkeypatch.setenv("KOHLE_PRICE_FILE", str(price_file))

    first = _fetch_prices(ledger, monkeypatch)

    assert first.exit_code == 0, first.output
    assert first.output.count("priced") == 2
    assert "file:XYZ" in first.output
    assert "previous none" in first.output
    with ledger() as session:
        assert sorted((p.price, p.source) for p in session.scalars(select(Price))) == [
            (Decimal(3), "file"),
            (Decimal("12.5"), "file"),
        ]

    with ledger() as session:
        groups_after_first = session.scalar(select(func.count()).select_from(OperationGroup))

    second = _fetch_prices(ledger, monkeypatch)

    assert second.exit_code == 0, second.output
    assert second.output.count("already stored") == 2
    with ledger() as session:
        assert len(session.scalars(select(Price)).all()) == 2
        assert session.scalar(select(func.count()).select_from(OperationGroup)) == groups_after_first


def test_unbound_only_exits_zero(ledger: sessionmaker, monkeypatch: pytest.MonkeyPatch) -> None:
    _hold(ledger, "X1")

    result = _fetch_prices(ledger, monkeypatch)

    assert result.exit_code == 0, result.output
    assert "unbound" in result.output


def test_unset_price_file_exits_one(
    ledger: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    _hold(ledger, "X1")
    _bind(ledger, monkeypatch, "X1", "XYZ")
    monkeypatch.delenv("KOHLE_PRICE_FILE", raising=False)

    result = _fetch_prices(ledger, monkeypatch)

    assert result.exit_code == 1
    assert "unpriced" in result.output
    assert "KOHLE_PRICE_FILE is not set" in result.output
    assert "1 held securities unpriced" in result.output
    with ledger() as session:
        assert session.scalars(select(Price)).all() == []


def test_rejected_file_close_exits_one_and_valid_unit_is_still_stored(
    ledger: sessionmaker, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with ledger() as session:
        AddUnit(session).execute("X2", "Y", UnitKind.security).unwrap()
    _hold(ledger, "X1", "X2")
    _bind(ledger, monkeypatch, "X1", "XYZ")
    _bind(ledger, monkeypatch, "X2", "ABC")
    price_file = tmp_path / "prices.csv"
    price_file.write_text("identifier,date,close\nXYZ,2026-03-02,0\nABC,2026-03-02,3\n", encoding="utf-8")
    monkeypatch.setenv("KOHLE_PRICE_FILE", str(price_file))

    result = _fetch_prices(ledger, monkeypatch)

    assert result.exit_code == 1
    assert "positive finite number" in result.output
    assert "1 held securities unpriced" in result.output
    with ledger() as session:
        assert [(p.price, p.source) for p in session.scalars(select(Price))] == [(Decimal(3), "file")]


class _AlphaFake:
    def __init__(self, bodies: dict[str, bytes]) -> None:
        self.bodies = bodies
        self.symbols: list[str] = []

    def __call__(self, url: str) -> bytes:
        symbol = parse_qs(urlparse(url).query)["symbol"][0]
        self.symbols.append(symbol)
        return self.bodies[symbol]


def _alpha_fetch(ledger: sessionmaker, monkeypatch: pytest.MonkeyPatch, fake: _AlphaFake):
    plugin = AlphaVantagePriceFetcher(http_get=fake, sleep=lambda _seconds: None)
    monkeypatch.setattr("kohle.app.cli.cli.load_price_plugins", lambda: {"alphavantage": plugin})
    monkeypatch.setenv("KOHLE_ALPHAVANTAGE_KEY", "TESTKEY")
    return CliRunner().invoke(cli, ["fetch-prices"], obj=ledger)


def _bind_alpha(ledger: sessionmaker, monkeypatch: pytest.MonkeyPatch) -> None:
    with ledger() as session:
        AddUnit(session).execute("X2", "Y", UnitKind.security).unwrap()
    _hold(ledger, "X1", "X2")
    monkeypatch.setattr("kohle.app.cli.cli.load_price_plugins", lambda: {"alphavantage": AlphaVantagePriceFetcher()})
    for unit, symbol in (("X1", "A"), ("X2", "B")):
        result = CliRunner().invoke(cli, ["set-price-source", unit, "alphavantage", symbol], obj=ledger)
        assert result.exit_code == 0, result.output


def _fixture(name: str) -> bytes:
    return (Path(__file__).parent / "fixtures" / "alphavantage" / name).read_bytes()


def test_alphavantage_throttle_scenario(ledger: sessionmaker, monkeypatch: pytest.MonkeyPatch) -> None:
    _bind_alpha(ledger, monkeypatch)
    fake = _AlphaFake({"A": _fixture("daily.json"), "B": _fixture("daily_limit.json")})

    result = _alpha_fetch(ledger, monkeypatch, fake)

    assert result.exit_code == 1
    assert fake.symbols == ["A", "B"]
    assert "1 held securities unpriced" in result.output
    assert "transient" in result.output
    assert "TESTKEY" not in result.output
    with ledger() as session:
        (stored,) = session.scalars(select(Price))
        assert (stored.unit.identifier, stored.price, stored.source) == ("X1", Decimal("227.1300"), "alphavantage")


def test_alphavantage_requests_the_unit_with_no_close_first(
    ledger: sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    _bind_alpha(ledger, monkeypatch)
    with ledger() as session:
        a = get_unit_by_identifier_service(DbTransactionContext(session), "X1").unwrap()
        session.add(Price(unit_id=a.id, price_date=date(2026, 10, 1), price=Decimal(5), source="alphavantage"))
        session.commit()
    fake = _AlphaFake({"A": _fixture("daily_limit.json"), "B": _fixture("daily.json")})

    result = _alpha_fetch(ledger, monkeypatch, fake)

    assert result.exit_code == 1
    assert fake.symbols == ["B", "A"]
    with ledger() as session:
        stored = {p.unit.identifier: p.price for p in session.scalars(select(Price))}
        assert stored == {"X1": Decimal(5), "X2": Decimal("227.1300")}


def test_nothing_held_says_so(ledger: sessionmaker, monkeypatch: pytest.MonkeyPatch) -> None:
    result = _fetch_prices(ledger, monkeypatch)

    assert result.exit_code == 0, result.output
    assert "No held securities" in result.output
