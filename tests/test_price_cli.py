"""Layer 3 — CLI through `CliRunner`.

`set-price-source` and `fetch-prices` (issues 029-033), design §5, §6.7, §15. `kohle.app.cli.cli.load_price_plugins` monkeypatched, as in the importer CLI tests.
"""

from collections.abc import Sequence

import pytest
from click.testing import CliRunner
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from kohle.app.cli.cli import cli
from kohle.core.result import Result
from kohle.domain.models import PriceBinding, UnitKind
from kohle.plugin.price_plugin import PriceFetcherPlugin, PriceFetchError, PriceResult
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


@pytest.mark.skip(reason="scaffold: issue 030")
def test_fetch_prices_with_the_file_plugin() -> None:
    # TODO(030) — one test per site:
    #   - real FilePriceFetcher, KOHLE_PRICE_FILE at a temp file: priced, then a re-run reports already stored for every unit
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 030")
def test_unbound_only_exits_zero() -> None:
    # TODO(030) — one test per site:
    #   - an unbound held unit is the only gap
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 030")
def test_unset_price_file_exits_one() -> None:
    # TODO(030) — one test per site:
    #   - message per unit
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 033")
def test_alphavantage_throttle_scenario() -> None:
    # TODO(033) — one test per site:
    #   - 033: exits 1 with one row stored (design §10.6)
    raise NotImplementedError


@pytest.mark.skip(reason="scaffold: issue 030")
def test_nothing_held_says_so() -> None:
    # TODO(030) — one test per site:
    #   - prints `No held securities`
    raise NotImplementedError
