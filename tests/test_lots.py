from datetime import date
from decimal import Decimal

import pytest

from kohle.domain.models import JournalEntry, JournalLine, Unit
from kohle.use_cases.lots import Lot, _take, realised_gain, replay

DEPOT = 1
OWN = {DEPOT: "Depot"}


def _line(line_id: int, day: int, quantity: str, price: str, *, is_debit: bool, account_id: int = DEPOT) -> JournalLine:
    return JournalLine(
        id=line_id,
        entry=JournalEntry(id=line_id, entry_date=date(2026, 1, day)),
        account_id=account_id,
        unit=Unit(identifier="X1"),
        unit_id=7,
        quantity=Decimal(quantity),
        unit_price=Decimal(price),
        is_debit=is_debit,
    )


def test_buy_buy_sell_gives_fifo_gain_and_remaining_lot_cost():
    lines = [
        _line(1, 1, "10", "100", is_debit=True),
        _line(2, 2, "10", "120", is_debit=True),
        _line(3, 3, "15", "130", is_debit=False),
    ]

    result = replay(lines, OWN).unwrap()

    (sale,) = result.sales
    assert (sale.proceeds, sale.fifo_cost, sale.gain) == (Decimal(1950), Decimal(1600), Decimal(350))
    assert (sale.entry_date, sale.account_name, sale.unit_identifier) == (date(2026, 1, 3), "Depot", "X1")
    (holding,) = result.holdings
    assert (holding.quantity, holding.fifo_cost) == (Decimal(5), Decimal(600))


def test_realised_gain_of_no_sales_is_zero():
    assert realised_gain([]) == Decimal(0)


def test_take_splits_a_lot_exactly():
    queue = [Lot(date(2026, 1, 1), 1, Decimal("0.3"), Decimal(7))]

    taken, shortfall = _take(queue, Decimal("0.1"))

    assert shortfall == 0
    assert sum(lot.quantity for lot in taken + queue) == Decimal("0.3")
    assert [lot.quantity for lot in taken] == [Decimal("0.1")]
    assert [lot.quantity for lot in queue] == [Decimal("0.2")]


@pytest.mark.skip(reason="issue 041")
def test_oversell_fails_naming_unit_account_date_and_shortfall():
    ...


@pytest.mark.skip(reason="issue 042")
def test_same_security_in_two_depots_replays_independently():
    ...


@pytest.mark.skip(reason="issue 042")
def test_own_depot_move_realises_nothing_and_carries_original_lots():
    ...


@pytest.mark.skip(reason="issue 042")
def test_unbalanced_own_move_fails():
    ...


@pytest.mark.skip(reason="issue 043")
def test_people_account_security_move_fails_naming_the_entry():
    ...
