"""Layer 1 — replay of currency lots (issues 111, 113, 115, 117). Design §3, §14."""

from datetime import date
from decimal import Decimal

import pytest

from kohle.domain.domain_errors import LotShortfall
from kohle.domain.models import JournalEntry, JournalLine, Unit, UnitKind
from kohle.use_cases.lots import _foreign_currency, replay


def _inr_line(line_id: int, day: int, quantity: str, cost: str, *, is_debit: bool) -> JournalLine:
    return JournalLine(
        id=line_id,
        entry=JournalEntry(id=line_id, entry_date=date(2026, 1, day)),
        account_id=1,
        unit=Unit(identifier="INR", kind=UnitKind.currency),
        unit_id=7,
        quantity=Decimal(quantity),
        unit_price=(Decimal(cost) / Decimal(quantity)).quantize(Decimal("0.00000001")),
        cost=Decimal(cost),
        is_debit=is_debit,
    )


INR_UNIT = 7
INFY_UNIT = 8
TCS_UNIT = 9
BANK = 1
DEMAT_CASH = 2
DEMAT = 3
OWN = {BANK: "IndianBank", DEMAT_CASH: "DematCash", DEMAT: "Demat"}


def _line(
    line_id: int, entry_id: int, day: int, account_id: int, identifier: str, quantity: str, *,
    is_debit: bool, price: str = "1", cost: str | None = None, priced_in_inr: bool = False,
) -> JournalLine:
    kinds = {"INR": (INR_UNIT, UnitKind.currency), "INFY": (INFY_UNIT, UnitKind.security), "TCS": (TCS_UNIT, UnitKind.security)}
    unit_id, kind = kinds[identifier]
    return JournalLine(
        id=line_id,
        entry=JournalEntry(id=entry_id, entry_date=date(2026, 1, day)),
        account_id=account_id,
        unit=Unit(identifier=identifier, kind=kind),
        unit_id=unit_id,
        quantity=Decimal(quantity),
        unit_price=Decimal(price),
        cost=None if cost is None else Decimal(cost),
        price_unit_id=INR_UNIT if priced_in_inr else None,
        is_debit=is_debit,
    )


def _remit(line_id: int, day: int, quantity: str, euros: str, account_id: int = BANK) -> JournalLine:
    return _line(line_id, line_id, day, account_id, "INR", quantity, is_debit=True, cost=euros)


def test_remittance_gives_one_exact_lot() -> None:
    result = replay([_inr_line(1, 1, "90000", "1000", is_debit=True)], {1: "IndianBank"}).unwrap()

    (holding,) = result.holdings
    assert (holding.unit_identifier, holding.quantity, holding.fifo_cost) == ("INR", Decimal(90000), Decimal(1000))
    assert result.sales == []


def test_purchase_takes_cost_from_inr_lots() -> None:
    lines = [
        _remit(1, 1, "90000", "1000"),
        _remit(2, 2, "100000", "1100"),
        _line(3, 3, 3, BANK, "INR", "120000", is_debit=False, priced_in_inr=True),
        _line(4, 3, 3, DEMAT, "INFY", "100", is_debit=True, price="1200", cost="120000", priced_in_inr=True),
    ]

    result = replay(lines, OWN).unwrap()

    holdings = {h.unit_identifier: (h.quantity, h.fifo_cost) for h in result.holdings}
    assert holdings == {"INR": (Decimal(70000), Decimal(770)), "INFY": (Decimal(100), Decimal(1330))}
    assert result.sales == []
    assert (result.costs[3], result.costs[4]) == (Decimal(1330), Decimal(1330))


def test_one_payment_for_two_stocks_apportions_exactly() -> None:
    lines = [
        _remit(1, 1, "90000", "1000"),
        _remit(2, 2, "100000", "1100"),
        _line(3, 3, 3, BANK, "INR", "120000", is_debit=False, priced_in_inr=True),
        _line(4, 3, 3, DEMAT, "INFY", "100", is_debit=True, price="900", cost="90000", priced_in_inr=True),
        _line(5, 3, 3, DEMAT, "TCS", "30", is_debit=True, price="1000", cost="30000", priced_in_inr=True),
    ]

    result = replay(lines, OWN).unwrap()

    assert (result.costs[4], result.costs[5]) == (Decimal("997.5"), Decimal("332.5"))
    assert result.costs[4] + result.costs[5] == result.costs[3] == Decimal(1330)
    holdings = {h.unit_identifier: h.fifo_cost for h in result.holdings}
    assert holdings["INFY"] == Decimal("997.5")
    assert holdings["TCS"] == Decimal("332.5")


def test_a_partial_load_still_gives_the_stock_its_own_share() -> None:
    # An at-par expense line on an account the ledger report does not load.
    lines = [
        _remit(1, 1, "90000", "1000"),
        _line(2, 2, 2, BANK, "INR", "30000", is_debit=False, priced_in_inr=True),
        _line(3, 2, 2, DEMAT, "INFY", "20", is_debit=True, price="1000", cost="20000", priced_in_inr=True),
    ]

    result = replay(lines, OWN).unwrap()

    assert result.costs[3] == Decimal(1000) * Decimal(20000) / Decimal(90000)
    (infy,) = (h for h in result.holdings if h.unit_identifier == "INFY")
    assert infy.fifo_cost == result.costs[3]


def test_reconversion_realises_fx_gain() -> None:
    lines = [
        _remit(1, 1, "90000", "1000"),
        _line(2, 2, 2, BANK, "INR", "45000", is_debit=False, cost="600"),
    ]

    result = replay(lines, OWN).unwrap()

    (sale,) = result.sales
    assert (sale.unit_identifier, sale.account_name, sale.quantity) == ("INR", "IndianBank", Decimal(45000))
    assert (sale.proceeds, sale.fifo_cost, sale.gain) == (Decimal(600), Decimal(500), Decimal(100))
    (holding,) = result.holdings
    assert (holding.quantity, holding.fifo_cost) == (Decimal(45000), Decimal(500))
    assert result.costs[2] == Decimal(500)


def test_move_between_own_accounts_carries_lots() -> None:
    lines = [
        _line(1, 1, 1, BANK, "INR", "10000", is_debit=True, cost="100"),
        _line(2, 2, 2, BANK, "INR", "10000", is_debit=True, cost="200"),
        _line(3, 3, 3, BANK, "INR", "15000", is_debit=False, priced_in_inr=True),
        _line(4, 3, 3, DEMAT_CASH, "INR", "15000", is_debit=True, priced_in_inr=True),
        _line(5, 4, 4, DEMAT_CASH, "INR", "12000", is_debit=False, priced_in_inr=True),
        _line(6, 4, 4, DEMAT, "INFY", "10", is_debit=True, price="1200", cost="12000", priced_in_inr=True),
    ]

    result = replay(lines, OWN).unwrap()

    assert result.sales == []
    assert (result.costs[3], result.costs[4]) == (Decimal(200), Decimal(200))
    # 10,000 at 0.01 and 2,000 at 0.02 from the lots that crossed.
    assert result.costs[5] == result.costs[6] == Decimal(140)
    holdings = {h.unit_identifier: (h.quantity, h.fifo_cost) for h in result.holdings}
    assert holdings["INR"] == (Decimal(8000), Decimal(160))


@pytest.mark.parametrize("cost", [None, "20"])
def test_payment_beyond_the_lots_is_a_shortfall(cost: str | None) -> None:
    # A payment is at par and a disposal states euros; both fail the same way.
    lines = [
        _remit(1, 1, "1000", "10"),
        _line(2, 2, 2, BANK, "INR", "1500", is_debit=False, cost=cost, priced_in_inr=cost is None),
    ]

    error = replay(lines, OWN).unwrap_err()

    assert isinstance(error, LotShortfall)
    assert str(error) == (
        "INR in 'IndianBank' on 2026-01-02: disposes of 500 more than the account holds; is an earlier purchase missing?"
    )


@pytest.mark.skip(reason="TODO scaffold: issue 117")
def test_people_account_is_refused() -> None:
    # TODO: CurrencyWithPeople for a People credit, a People debit and a People-only entry
    raise NotImplementedError


def test_security_shortfall_is_ignored_when_only_currencies_are_replayed() -> None:
    lines = [
        _remit(1, 1, "90000", "1000"),
        _line(2, 2, 2, DEMAT, "INFY", "10", is_debit=False, price="1200"),
    ]

    assert isinstance(replay(lines, OWN).unwrap_err(), LotShortfall)
    result = replay(lines, OWN, lots_for=_foreign_currency).unwrap()
    assert [h.unit_identifier for h in result.holdings] == ["INR"]
