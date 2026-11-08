"""Layer 2 — quote currency on bindings and closes (issues 107, 108). Design §5, §14."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from kohle.app.plugins.kohle_alphavantage_price_fetcher import AlphaVantagePriceFetcher
from kohle.app.plugins.kohle_file_price_fetcher import FilePriceFetcher, MalformedPriceFile
from kohle.core.result import Result
from kohle.domain.domain_errors import NonBaseCurrency, NotAQuoteCurrency, NotASecurityUnit, RateNotQuotedInEur
from kohle.domain.models import Account, AccountType, Operation, Price, PriceBinding, Unit, UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.plugin.price_plugin import Close, PriceFetcherPlugin, PriceFetchError, PriceResult
from kohle.services.account_services import add_account_service
from kohle.services.journal_services import LineSpec, add_journal_entry_service
from kohle.services.unit_services import add_unit_service
from kohle.use_cases.prices import (
    AppendPrices,
    ListPriceTargets,
    Priced,
    SetPriceSource,
    Unpriced,
    call_price_plugins,
)

DAY = date(2026, 3, 2)
TODAY = date(2026, 3, 3)
PLUGINS = ["alphavantage", "file"]


class _Plugin(PriceFetcherPlugin):
    """Reports `currency` for every symbol; records the quote currencies core handed it."""

    def __init__(self, currency: str) -> None:
        self.currency = currency
        self.received: dict[str, str] = {}

    @property
    def name(self) -> str:
        return "file"

    def fetch_latest_closes(self, symbols: Sequence[str]) -> Result[dict[str, PriceResult], PriceFetchError]:
        return Result.ok(
            {s: Close(price_date=DAY, price=Decimal(100), currency=self.currency) for s in symbols}
        )

    def fetch_bound_closes(self, symbols, quote_currencies):
        self.received = dict(quote_currencies)
        return self.fetch_latest_closes(symbols)


@pytest.fixture
def held(session: Session) -> Session:
    """X1 held and bound to `file`; EUR and INR are currency units, GOLD a commodity."""
    ctx = DbTransactionContext(session)
    depot = add_account_service(ctx, "Depot", AccountType.asset).unwrap()
    cash = add_account_service(ctx, "Cash", AccountType.asset).unwrap()
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap()
    add_unit_service(ctx, "INR", "Indian rupee", UnitKind.currency).unwrap()
    add_unit_service(ctx, "GOLD", "Gold", UnitKind.commodity).unwrap()
    x1 = add_unit_service(ctx, "X1", "Thing", UnitKind.security).unwrap()
    add_journal_entry_service(
        ctx, date(2026, 1, 1), "buy", "buy X1",
        [
            LineSpec(depot.id, x1.id, Decimal(1), Decimal(10), is_debit=True),
            LineSpec(cash.id, eur.id, Decimal(10), Decimal(1), is_debit=False),
        ],
    ).unwrap()
    session.commit()
    return session


def _bind(session: Session, quote: str | None = None):
    args = () if quote is None else (quote,)
    return SetPriceSource(session).execute("X1", "file", "XYZ", PLUGINS, *args)


def _fetch(session: Session, plugin: _Plugin):
    targets = ListPriceTargets(session).execute().unwrap()
    fetched = call_price_plugins(targets, {"file": plugin})
    return AppendPrices(session).execute(targets, fetched, TODAY).unwrap()


def _prices(session: Session) -> list[tuple[date, Decimal, str]]:
    return [(p.price_date, p.price, p.currency) for p in session.scalars(select(Price).order_by(Price.price_date))]


def test_inr_close_for_a_eur_binding_is_rejected(held: Session) -> None:
    _bind(held).unwrap()

    report = _fetch(held, _Plugin("INR"))

    (outcome,) = report.outcomes
    assert isinstance(outcome, Unpriced)
    assert isinstance(outcome.reason, NonBaseCurrency)
    assert (outcome.reason.currency, outcome.reason.base) == ("INR", "EUR")
    assert "INR" in str(outcome.reason)
    assert _prices(held) == []


def test_eur_close_for_an_inr_binding_is_rejected(held: Session) -> None:
    _bind(held, "INR").unwrap()

    report = _fetch(held, _Plugin("EUR"))

    (outcome,) = (o for o in report.outcomes if o.unit.identifier == "X1")
    assert isinstance(outcome, Unpriced)
    assert isinstance(outcome.reason, NonBaseCurrency)
    assert (outcome.reason.currency, outcome.reason.base) == ("EUR", "INR")
    assert _prices(held) == []


def test_a_close_in_the_bindings_currency_is_stored_with_it(held: Session) -> None:
    _bind(held, "INR").unwrap()
    plugin = _Plugin("INR")

    report = _fetch(held, plugin)

    (outcome,) = (o for o in report.outcomes if o.unit.identifier == "X1")
    assert isinstance(outcome, Priced)
    assert plugin.received == {"XYZ": "INR"}
    assert _prices(held) == [(DAY, Decimal(100), "INR")]


def test_set_price_source_binds_in_eur_by_default_and_refuses_other_quotes(held: Session) -> None:
    default = _bind(held).unwrap()
    assert default.quote_currency == "EUR"

    inr = _bind(held, "INR").unwrap()
    assert inr.quote_currency == "INR"

    for bad in ("NOPE", "X1", "GOLD"):
        assert isinstance(_bind(held, bad).unwrap_err(), NotAQuoteCurrency)
    (binding,) = held.scalars(select(PriceBinding)).all()
    assert binding.quote_currency == "INR"

    for unit in ("EUR", "GOLD"):
        err = SetPriceSource(held).execute(unit, "file", "XYZ", PLUGINS).unwrap_err()
        assert isinstance(err, NotASecurityUnit)


def test_an_identical_rebind_writes_nothing_but_a_new_quote_currency_updates(held: Session) -> None:
    _bind(held, "INR").unwrap()
    operations = len(held.scalars(select(Operation)).all())

    _bind(held, "INR").unwrap()
    assert len(held.scalars(select(Operation)).all()) == operations

    _bind(held, "EUR").unwrap()
    assert len(held.scalars(select(Operation)).all()) == operations + 1


def test_rebinding_keeps_each_rows_own_currency(held: Session) -> None:
    _bind(held, "INR").unwrap()
    _fetch(held, _Plugin("INR"))

    rebound = _bind(held, "EUR")

    assert rebound.is_ok
    held.add(Price(unit_id=held.scalars(select(PriceBinding.unit_id)).one(), price_date=date(2026, 3, 3),
                   price=Decimal(2), source="file", currency="EUR"))
    held.commit()
    assert _prices(held) == [(DAY, Decimal(100), "INR"), (date(2026, 3, 3), Decimal(2), "EUR")]


def test_list_price_targets_includes_a_currency_only_held_via_shares(held: Session) -> None:
    _bind(held, "INR").unwrap()
    SetPriceSource(held).execute("INR", "file", "INREUR", PLUGINS).unwrap()

    targets = ListPriceTargets(held).execute().unwrap()

    assert {s: [u.identifier for u in units] for s, units in targets.by_plugin["file"].items()} == {
        "XYZ": ["X1"],
        "INREUR": ["INR"],
    }
    assert targets.unbound == []


def test_an_unbound_quote_currency_is_a_target_and_eur_never_is(held: Session) -> None:
    _bind(held, "INR").unwrap()

    targets = ListPriceTargets(held).execute().unwrap()

    assert [u.identifier for u in targets.unbound] == ["INR"]


def test_a_held_currency_unit_is_a_target_alongside_a_share(held: Session) -> None:
    ctx = DbTransactionContext(held)
    rupees = add_account_service(ctx, "Rupees", AccountType.asset).unwrap()
    cash = held.scalars(select(Account).where(Account.name == "Cash")).one()
    eur, inr = (held.scalars(select(Unit).where(Unit.identifier == i)).one() for i in ("EUR", "INR"))
    add_journal_entry_service(
        ctx, date(2026, 1, 2), "remit", "remit",
        [
            LineSpec(rupees.id, inr.id, Decimal(100), Decimal("0.01"), is_debit=True),
            LineSpec(cash.id, eur.id, Decimal(1), Decimal(1), is_debit=False),
        ],
    ).unwrap()
    held.commit()

    targets = ListPriceTargets(held).execute().unwrap()

    assert [u.identifier for u in targets.unbound] == ["INR", "X1"]


def test_a_rate_is_bound_in_eur_and_stored_as_an_ordinary_price(held: Session) -> None:
    SetPriceSource(held).execute("INR", "file", "INREUR", PLUGINS).unwrap()
    _bind(held, "INR").unwrap()

    report = _fetch(held, _Plugin("EUR"))

    outcomes = {o.unit.identifier: o for o in report.outcomes}
    assert isinstance(outcomes["INR"], Priced)
    assert isinstance(outcomes["X1"], Unpriced)
    (price,) = held.scalars(select(Price)).all()
    inr_id = held.scalars(select(Unit.id).where(Unit.identifier == "INR")).one()
    assert (price.currency, price.unit_id) == ("EUR", inr_id)


def test_a_rate_cannot_be_quoted_outside_eur(held: Session) -> None:
    err = SetPriceSource(held).execute("INR", "file", "INREUR", PLUGINS, "INR").unwrap_err()

    assert isinstance(err, RateNotQuotedInEur)
    assert "INR" in str(err)
    assert held.scalars(select(PriceBinding)).all() == []


def _price_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    path = tmp_path / "prices.csv"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setenv("KOHLE_PRICE_FILE", str(path))


def test_file_plugin_currency_column(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _price_file(
        tmp_path, monkeypatch,
        "identifier,date,close,currency\nA,2026-03-02,10,INR\nB,2026-03-02,20,\nC,2026-03-02,30,EUR\n",
    )

    got = FilePriceFetcher().fetch_latest_closes(["A", "B", "C"]).unwrap()

    assert [got[s].currency for s in "ABC"] == ["INR", "EUR", "EUR"]  # type: ignore[union-attr]


def test_file_plugin_three_column_header_still_means_eur(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _price_file(tmp_path, monkeypatch, "identifier,date,close\nA,2026-03-02,10\n")

    got = FilePriceFetcher().fetch_latest_closes(["A"]).unwrap()

    assert got["A"].currency == "EUR"  # type: ignore[union-attr]


def test_file_plugin_other_headers_and_short_rows_are_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _price_file(tmp_path, monkeypatch, "identifier,date,close,ccy\nA,2026-03-02,10,INR\n")
    assert isinstance(FilePriceFetcher().fetch_latest_closes(["A"]).unwrap_err(), MalformedPriceFile)

    _price_file(tmp_path, monkeypatch, "identifier,date,close,currency\nA,2026-03-02,10\n")
    assert isinstance(FilePriceFetcher().fetch_latest_closes(["A"]).unwrap_err(), MalformedPriceFile)


def test_alphavantage_stamps_the_bindings_currency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KOHLE_ALPHAVANTAGE_KEY", "TESTKEY")
    body = (Path(__file__).parent / "fixtures" / "alphavantage" / "daily.json").read_bytes()
    plugin = AlphaVantagePriceFetcher(http_get=lambda _: body, sleep=lambda _: None)

    bound = plugin.fetch_bound_closes(["IBM"], {"IBM": "INR"}).unwrap()
    default = plugin.fetch_latest_closes(["IBM"]).unwrap()

    assert bound["IBM"].currency == "INR"  # type: ignore[union-attr]
    assert default["IBM"].currency == "EUR"  # type: ignore[union-attr]


def test_a_plugin_that_only_has_fetch_latest_closes_is_called_through_the_default(held: Session) -> None:
    class Plain(PriceFetcherPlugin):
        name = "file"  # type: ignore[assignment]

        def fetch_latest_closes(self, symbols):
            return Result.ok({s: Close(price_date=DAY, price=Decimal(1), currency="EUR") for s in symbols})

    _bind(held).unwrap()
    targets = ListPriceTargets(held).execute().unwrap()

    fetched = call_price_plugins(targets, {"file": Plain()})

    assert fetched["file"].unwrap()["XYZ"].currency == "EUR"  # type: ignore[union-attr]


def test_cli_set_price_source_currency_and_fetch_prices_suffix(
    held: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pin_today
) -> None:
    from click.testing import CliRunner

    from kohle.app.cli.cli import cli

    monkeypatch.setattr("kohle.app.cli.cli.load_price_plugins", lambda: {"file": _Plugin("INR")})
    engine = held.get_bind()
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    pin_today(TODAY)
    runner = CliRunner()

    refused = runner.invoke(cli, ["set-price-source", "X1", "file", "XYZ", "--currency", "NOPE"], obj=factory)
    bound = runner.invoke(cli, ["set-price-source", "X1", "file", "XYZ", "--currency", "INR"], obj=factory)
    fetched = runner.invoke(cli, ["fetch-prices"], obj=factory)

    assert refused.exit_code != 0
    assert "cannot be a quote currency" in refused.output
    assert bound.exit_code == 0, bound.output
    assert fetched.exit_code == 0, fetched.output
    assert "100 INR" in fetched.output
