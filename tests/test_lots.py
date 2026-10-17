from datetime import date
from decimal import Decimal

import pytest

from kohle.domain.domain_errors import LotShortfall, UnbalancedOwnMove
from kohle.domain.models import JournalEntry, JournalLine, Unit
from kohle.use_cases.lots import Lot, _take, realised_gain, replay

DEPOT = 1
OWN = {DEPOT: "Depot"}


def _line(line_id: int, day: int, quantity: str, price: str, *, is_debit: bool, account_id: int = DEPOT, entry_id: int | None = None) -> JournalLine:
    return JournalLine(
        id=line_id,
        entry=JournalEntry(id=line_id if entry_id is None else entry_id, entry_date=date(2026, 1, day)),
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


def test_oversell_fails_naming_unit_account_date_and_shortfall():
    lines = [
        _line(1, 1, "10", "100", is_debit=True),
        _line(2, 2, "15", "130", is_debit=False),
    ]

    error = replay(lines, OWN).unwrap_err()

    assert isinstance(error, LotShortfall)
    assert str(error) == (
        "X1 in 'Depot' on 2026-01-02: disposes of 5 more than the account holds; is an earlier purchase missing?"
    )


DEPOT_B = 2
TWO_DEPOTS = {DEPOT: "Depot", DEPOT_B: "DepotB"}


def test_same_security_in_two_depots_replays_independently():
    lines = [
        _line(1, 1, "10", "100", is_debit=True),
        _line(2, 2, "10", "120", is_debit=True, account_id=DEPOT_B),
        _line(3, 3, "5", "130", is_debit=False, account_id=DEPOT_B),
    ]

    result = replay(lines, TWO_DEPOTS).unwrap()

    (sale,) = result.sales
    assert (sale.account_name, sale.fifo_cost) == ("DepotB", Decimal(600))
    (holding,) = result.holdings
    assert (holding.quantity, holding.fifo_cost) == (Decimal(15), Decimal(1600))


def test_own_depot_move_realises_nothing_and_carries_original_lots():
    lines = [
        _line(1, 1, "10", "100", is_debit=True),
        _line(2, 2, "10", "120", is_debit=True),
        _line(3, 3, "15", "999", is_debit=False, entry_id=3),
        _line(4, 3, "15", "999", is_debit=True, account_id=DEPOT_B, entry_id=3),
        _line(5, 4, "12", "130", is_debit=False, account_id=DEPOT_B),
    ]

    result = replay(lines, TWO_DEPOTS).unwrap()

    (sale,) = result.sales
    assert (sale.account_name, sale.fifo_cost, sale.gain) == ("DepotB", Decimal(1240), Decimal(320))
    (holding,) = result.holdings
    assert (holding.quantity, holding.fifo_cost) == (Decimal(8), Decimal(960))


def test_move_out_larger_than_the_depot_holds_fails():
    lines = [
        _line(1, 1, "5", "100", is_debit=True),
        _line(2, 2, "8", "1", is_debit=False, entry_id=2),
        _line(3, 2, "8", "1", is_debit=True, account_id=DEPOT_B, entry_id=2),
    ]

    error = replay(lines, TWO_DEPOTS).unwrap_err()

    assert isinstance(error, LotShortfall)
    assert error.shortfall == Decimal(3)


def test_unbalanced_own_move_fails():
    lines = [
        _line(1, 1, "10", "100", is_debit=True),
        _line(2, 2, "10", "1", is_debit=False, entry_id=2),
        _line(3, 2, "6", "1", is_debit=True, account_id=DEPOT_B, entry_id=2),
    ]

    error = replay(lines, TWO_DEPOTS).unwrap_err()

    assert isinstance(error, UnbalancedOwnMove)
    assert str(error) == (
        "Entry 2 on 2026-01-02 moves 10 X1 out of own accounts but 6 in; "
        "record the move and any sale or purchase as separate entries"
    )


@pytest.mark.skip(reason="issue 043")
def test_people_account_security_move_fails_naming_the_entry():
    ...
