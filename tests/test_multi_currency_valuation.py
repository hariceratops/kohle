"""Layer 1/2 — valuing holdings quoted in another currency, and subtotals (issues 120, 121, 122, 123). Design §8, §14."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from kohle.domain.models import AccountType, Price, UnitKind
from kohle.infrastructure.transaction_context import DbTransactionContext
from kohle.services.account_services import add_account_service
from kohle.services.journal_services import LineSpec, add_journal_entry_service
from kohle.services.price_services import add_price_service, set_price_binding_service
from kohle.services.unit_services import (
    add_unit_service,
    get_unit_by_identifier_service,
)
from kohle.use_cases.journal import UnitBalance
from kohle.use_cases.prices import Fresh, NoClose, Stale
from kohle.use_cases.reporting import (
    NetWorthHistory,
    QueryValuedBalance,
    Subtotal,
    ValuedBalance,
    ValuedNetWorth,
    holding_currencies,
    subtotals,
    summarise,
    valuation_status,
)

TODAY = date(2026, 3, 10)


def _price(day: date, price: str = "1", currency: str = "EUR") -> Price:
    return Price(
        unit_id=1,
        price_date=day,
        price=Decimal(price),
        source="file",
        currency=currency,
    )


def _balance(identifier: str, quantity: str, average_cost: str) -> UnitBalance:
    return UnitBalance(identifier, Decimal(quantity), Decimal(average_cost), 1)


def test_valuation_status_without_a_rate_is_the_close() -> None:
    close = Stale(_price(date(2026, 1, 1)))
    assert valuation_status(close, None) is close
    assert valuation_status(None, None) is None


def test_status_is_the_worse_of_close_and_rate() -> None:
    old, mid, new = date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 9)
    fresh_close, fresh_rate = Fresh(_price(new)), Fresh(_price(new))

    assert valuation_status(fresh_close, fresh_rate) is fresh_close
    assert valuation_status(fresh_close, NoClose()) == NoClose()
    assert valuation_status(NoClose(), fresh_rate) == NoClose()
    assert valuation_status(NoClose(), NoClose()) == NoClose()
    assert valuation_status(Stale(_price(old)), NoClose()) == NoClose()

    # A stale rate beside a fresh close shows the rate's date, and the other way round.
    assert valuation_status(fresh_close, Stale(_price(mid))) == Stale(_price(mid))
    assert valuation_status(Stale(_price(mid)), fresh_rate) == Stale(_price(mid))
    # Both stale: the older date.
    assert valuation_status(Stale(_price(mid)), Stale(_price(old))) == Stale(
        _price(old)
    )
    assert valuation_status(Stale(_price(old)), Stale(_price(mid))) == Stale(
        _price(old)
    )


def test_pure_market_value_is_quantity_times_close_times_rate() -> None:
    row = ValuedBalance(
        _balance("X1", "2", "10"),
        Fresh(_price(TODAY, "5000", "INR")),
        Fresh(_price(TODAY, "0.011")),
    )
    assert row.market_value == Decimal(110)


@pytest.mark.parametrize("missing", ["close", "rate"])
def test_pure_missing_close_or_rate_falls_back_to_cost(missing: str) -> None:
    close = NoClose() if missing == "close" else Fresh(_price(TODAY, "5000", "INR"))
    rate = NoClose() if missing == "rate" else Fresh(_price(TODAY, "0.011"))
    row = ValuedBalance(_balance("X1", "2", "10"), close, rate)
    assert row.market_value == Decimal(20)
    assert row.status == NoClose()
    assert summarise([row]).no_price == 1


@pytest.fixture
def ledger(session: Session, people_root) -> Session:
    """Account Cash holds 2000 EUR; Depot holds 2 X1 (quoted in INR) and 90,000 INR."""
    ctx = DbTransactionContext(session)
    depot = add_account_service(ctx, "Depot", AccountType.asset).unwrap()
    cash = add_account_service(ctx, "Cash", AccountType.asset).unwrap()
    equity = add_account_service(ctx, "Salary", AccountType.income).unwrap()
    eur = add_unit_service(ctx, "EUR", "Euro", UnitKind.currency).unwrap()
    inr = add_unit_service(ctx, "INR", "Indian rupee", UnitKind.currency).unwrap()
    x1 = add_unit_service(ctx, "X1", "Thing", UnitKind.security).unwrap()
    add_journal_entry_service(
        ctx,
        date(2026, 1, 1),
        "open",
        "open",
        [
            LineSpec(cash.id, eur.id, Decimal(2000), Decimal(1), is_debit=True),
            LineSpec(equity.id, eur.id, Decimal(2000), Decimal(1), is_debit=False),
        ],
    ).unwrap()
    add_journal_entry_service(
        ctx,
        date(2026, 1, 2),
        "buy",
        "buy X1",
        [
            LineSpec(depot.id, x1.id, Decimal(2), Decimal(10), is_debit=True),
            LineSpec(cash.id, eur.id, Decimal(20), Decimal(1), is_debit=False),
        ],
    ).unwrap()
    add_journal_entry_service(
        ctx,
        date(2026, 1, 3),
        "remit",
        "remit",
        [
            LineSpec(
                depot.id,
                inr.id,
                Decimal(90000),
                Decimal(0),
                is_debit=True,
                cost=Decimal(1000),
            ),
            LineSpec(cash.id, eur.id, Decimal(1000), Decimal(1), is_debit=False),
        ],
    ).unwrap()
    session.commit()
    return session


def _add(
    session: Session, identifier: str, day: date, price: str, currency: str
) -> None:
    ctx = DbTransactionContext(session)
    unit = get_unit_by_identifier_service(ctx, identifier).unwrap()
    add_price_service(ctx, unit.id, day, Decimal(price), "file", currency).unwrap()
    session.commit()


def _rows(session: Session) -> dict[str, ValuedBalance]:
    valued = QueryValuedBalance(session).execute("Depot", TODAY, 7).unwrap()
    return {v.balance.unit_identifier: v for v in valued}


def test_market_value_is_quantity_times_close_times_rate(ledger: Session) -> None:
    # Older prices must lose to the latest on or before the date; later ones are ignored.
    _add(ledger, "X1", date(2026, 3, 1), "4000", "INR")
    _add(ledger, "X1", date(2026, 3, 9), "5000", "INR")
    _add(ledger, "X1", date(2026, 3, 11), "9999", "INR")
    _add(ledger, "INR", date(2026, 3, 5), "0.010", "EUR")
    _add(ledger, "INR", date(2026, 3, 8), "0.011", "EUR")

    rows = _rows(ledger)

    assert rows["X1"].market_value == Decimal(2) * Decimal(5000) * Decimal("0.011")
    assert rows["INR"].market_value == Decimal(90000) * Decimal("0.011")
    assert isinstance(rows["X1"].status, Fresh)
    assert isinstance(rows["INR"].status, Fresh)


def test_closes_and_rates_need_not_share_a_date(ledger: Session) -> None:
    _add(ledger, "X1", date(2026, 3, 9), "5000", "INR")
    _add(ledger, "INR", date(2026, 3, 3), "0.011", "EUR")  # 7 days old: still fresh

    assert _rows(ledger)["X1"].market_value == Decimal(110)


def test_stale_rate_makes_the_row_stale_at_the_rates_date(ledger: Session) -> None:
    _add(ledger, "X1", date(2026, 3, 9), "5000", "INR")
    _add(ledger, "INR", date(2026, 2, 1), "0.011", "EUR")

    row = _rows(ledger)["X1"]

    assert isinstance(row.status, Stale)
    assert row.status.close.price_date == date(2026, 2, 1)
    assert row.market_value == Decimal(110)


def test_missing_close_or_rate_falls_back_to_cost(ledger: Session) -> None:
    # No rate stored at all: the stock falls back to its euro cost (2 x 10) and so does the rupee cash.
    _add(ledger, "X1", date(2026, 3, 9), "5000", "INR")

    rows = _rows(ledger)

    assert rows["X1"].status == NoClose()
    assert rows["X1"].market_value == Decimal(20)
    assert rows["INR"].status == NoClose()
    assert round(rows["INR"].market_value, 6) == Decimal(1000)


def test_a_rate_without_a_close_leaves_the_stock_at_cost(ledger: Session) -> None:
    _add(ledger, "INR", date(2026, 3, 8), "0.011", "EUR")

    rows = _rows(ledger)

    assert rows["X1"].status == NoClose()
    assert rows["X1"].market_value == Decimal(20)
    assert rows["INR"].market_value == Decimal(990)


def test_net_worth_totals_the_converted_values(ledger: Session) -> None:
    _add(ledger, "X1", date(2026, 3, 9), "5000", "INR")
    _add(ledger, "INR", date(2026, 3, 8), "0.011", "EUR")

    report = ValuedNetWorth(ledger).execute(TODAY, 7).unwrap()

    # 980 EUR cash + 110 for X1 + 990 for the rupees
    assert report.net_worth_at_market == Decimal(2080)
    assert report.estimates.estimated == 0


def test_subtotals_give_native_and_euro_figures_per_currency(ledger: Session) -> None:
    _add(ledger, "X1", date(2026, 3, 9), "5000", "INR")
    _add(ledger, "INR", date(2026, 3, 8), "0.011", "EUR")
    ctx = DbTransactionContext(ledger)
    x1 = get_unit_by_identifier_service(ctx, "X1").unwrap()
    set_price_binding_service(ctx, x1.id, "file", "X1", "INR").unwrap()
    ledger.commit()

    report = ValuedNetWorth(ledger).execute(TODAY, 7).unwrap()

    eur, inr = report.subtotals
    assert (eur.currency, eur.native, eur.euro) == ("EUR", Decimal(980), Decimal(980))
    assert (inr.currency, inr.native, inr.euro) == ("INR", Decimal(100000), Decimal(1100))
    assert sum(s.euro for s in report.subtotals) == report.net_worth_at_market


def test_subtotals_show_a_dash_when_a_member_has_no_close_in_the_currency() -> None:
    inr, x1 = _balance("INR", "90000", "0"), UnitBalance("X1", Decimal(2), Decimal(10), 2)
    rows = [
        ValuedBalance(inr, NoClose(), NoClose()),
        ValuedBalance(x1, NoClose()),
    ]

    result = subtotals(rows, {1: "INR", 2: "INR"})

    assert result == [Subtotal("INR", None, Decimal(20) + Decimal(90000) * 0)]


def test_subtotal_counts_a_zero_row_as_zero_and_a_currency_as_its_quantity() -> None:
    inr = UnitBalance("INR", Decimal(500), Decimal(0), 1, UnitKind.currency)
    zero = UnitBalance("X1", Decimal(0), None, 2)
    rows = [
        ValuedBalance(inr, Fresh(_price(TODAY, "0.01")), None),
        ValuedBalance(zero, None),
    ]

    result = subtotals(rows, {1: "INR", 2: "INR"})

    assert result == [Subtotal("INR", Decimal(500), Decimal(5))]


def test_subtotals_are_empty_when_every_holding_is_in_euros() -> None:
    eur = UnitBalance("EUR", Decimal(100), Decimal(1), 1, UnitKind.currency)
    stock = UnitBalance("X1", Decimal(2), Decimal(10), 2)
    rows = [ValuedBalance(eur, None), ValuedBalance(stock, Fresh(_price(TODAY, "12")))]

    assert subtotals(rows, {1: "EUR", 2: "EUR"}) == []


def test_unbound_security_and_euro_cash_group_under_euro(ledger: Session) -> None:
    ctx = DbTransactionContext(ledger)
    depot = [
        b for b in QueryValuedBalance(ledger).execute("Depot", TODAY, 7).unwrap()
    ]
    currencies = holding_currencies(ctx, depot).unwrap()
    assert currencies == {b.balance.unit_id: b.balance.unit_identifier if b.balance.kind is UnitKind.currency else "EUR" for b in depot}


def test_history_values_each_date_at_its_own_close_and_rate(ledger: Session, start_state) -> None:
    _add(ledger, "X1", date(2026, 2, 10), "4000", "INR")
    _add(ledger, "INR", date(2026, 2, 10), "0.010", "EUR")
    _add(ledger, "X1", date(2026, 3, 1), "5000", "INR")
    _add(ledger, "INR", date(2026, 3, 1), "0.011", "EUR")

    rows = NetWorthHistory(ledger).execute(date(2026, 1, 10), TODAY, 30).unwrap()
    by_date = {r.on: r.report for r in rows}

    # Jan 15 predates every close and rate: all three holdings fall back to cost (980 + 20 + 1000).
    assert by_date[date(2026, 1, 15)].net_worth_at_market == Decimal(2000)
    assert by_date[date(2026, 1, 15)].estimates.estimated == 2
    # Feb 15 uses the 10 Feb close and rate; the 1 Mar ones are later and ignored.
    assert by_date[date(2026, 2, 15)].net_worth_at_market == Decimal(980 + 80 + 900)
    assert by_date[date(2026, 2, 15)].estimates.estimated == 0
    # The final row uses the 1 Mar close and rate.
    assert by_date[TODAY].net_worth_at_market == Decimal(2080)
    assert by_date[TODAY].net_worth_at_market == (
        ValuedNetWorth(ledger).execute(TODAY, 30).unwrap().net_worth_at_market
    )


def _positions_ledger(session_factory, rate: str | None) -> None:
    from datetime import timedelta

    from click.testing import CliRunner

    from kohle.app.cli.cli import cli

    for args in (
        ["add-account", "People", "--type", "asset"],
        ["add-account", "Girokonto", "--type", "asset"],
        ["add-account", "Demat", "--type", "asset"],
        ["add-account", "Opening", "--type", "income"],
        ["add-unit", "EUR", "Euro", "--kind", "currency"],
        ["add-unit", "INR", "Indian rupee", "--kind", "currency"],
        ["add-unit", "INFY", "Infosys", "--kind", "security"],
        ["record", "2026-01-01", "Opening", "1000", "--from", "Opening", "--to", "Girokonto"],
        ["record", "2026-01-02", "Remit", "90000", "--from", "Girokonto", "--to", "Demat", "--to-unit", "INR", "--total", "1000"],
        ["record", "2026-01-03", "Opening", "100", "--from", "Opening", "--to", "Demat", "--to-unit", "INFY", "--total", "1500"],
    ):
        result = CliRunner().invoke(cli, args, obj=session_factory)
        assert result.exit_code == 0, result.output
    today = date.today()  # noqa: DTZ011 - matches the CLI's own clock
    with session_factory() as session:
        ctx = DbTransactionContext(session)
        infy = get_unit_by_identifier_service(ctx, "INFY").unwrap()
        add_price_service(ctx, infy.id, today - timedelta(days=1), Decimal(1500), "file", "INR").unwrap()
        if rate is not None:
            inr = get_unit_by_identifier_service(ctx, "INR").unwrap()
            add_price_service(ctx, inr.id, today - timedelta(days=1), Decimal(rate), "file", "EUR").unwrap()
        session.commit()


def test_positions_label_the_quote_currency_and_list_inr_cash(session_factory) -> None:
    from click.testing import CliRunner

    from kohle.app.cli.cli import cli

    _positions_ledger(session_factory, "0.0104")

    result = CliRunner().invoke(cli, ["positions"], obj=session_factory)

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0].split()[:5] == ["unit", "quantity", "price", "quoted", "in"]
    rows = {line.split()[0]: line.split() for line in lines[2:4]}
    # price in the quote currency; market value, FIFO cost and gain in euros
    assert rows["INFY"][2:4] == ["1500.00", "INR"]
    assert {"1560.00", "1500.00", "60.00"} <= set(rows["INFY"])
    assert rows["INR"][2:4] == ["0.01040000", "EUR"]
    assert {"936.00", "1000.00", "-64.00"} <= set(rows["INR"])


def test_positions_without_a_foreign_close_have_no_quoted_in_column(session_factory) -> None:
    from click.testing import CliRunner

    from kohle.app.cli.cli import cli

    _positions_ledger(session_factory, None)
    # drop the INFY INR close so every close is in euros
    with session_factory() as session:
        for price in session.query(Price).all():
            session.delete(price)
        session.commit()

    result = CliRunner().invoke(cli, ["positions"], obj=session_factory)

    assert result.exit_code == 0, result.output
    assert "quoted" not in result.output


def test_positions_and_net_worth_print_subtotals_but_balance_does_not(session_factory) -> None:
    from click.testing import CliRunner

    from kohle.app.cli.cli import cli

    _positions_ledger(session_factory, "0.0104")
    with session_factory() as session:
        ctx = DbTransactionContext(session)
        infy = get_unit_by_identifier_service(ctx, "INFY").unwrap()
        set_price_binding_service(ctx, infy.id, "file", "INFY", "INR").unwrap()
        session.commit()
    run = lambda *a: CliRunner().invoke(cli, list(a), obj=session_factory)

    for command in ("positions", "net-worth"):
        result = run(command)
        assert result.exit_code == 0, result.output
        table = result.output.split("holdings estimated")[1].split("\n\n")[1].strip().splitlines()
        assert table[0].split() == ["currency", "market", "value", "in", "EUR"]
        rows = {line.split()[0]: line.split() for line in table[2:]}
        assert rows["INR"][1:] == ["240000.00", "2496.00"]

    assert "in EUR" not in run("balance", "Demat").output
    assert "in EUR" not in run("net-worth-history", "--from", "2026-01-01", "--to", "2026-01-31").output
