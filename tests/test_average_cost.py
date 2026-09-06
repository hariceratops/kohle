"""Layer 1 — pure unit tests, no fixture.

The moving-average cost fold (issue 005). The spec's wording admitted three
readings that diverge; the design chose moving average because it is the only
one where sale price cannot contaminate cost basis. These cases are where the
spec was underspecified, so they are the ones worth pinning down.
See dev/design/cli-record-and-balances.md section 6.4.

Issue 002 only builds the quantity-aggregation half of `_aggregate_by_unit`
(a straightforward sum, not yet the moving-average fold); those cases are
covered here. The average-cost cases above stay TODO for issue 005.
"""

from decimal import Decimal

from kohle.domain.models import JournalLine, Unit, UnitKind
from kohle.use_cases.journal import _aggregate_by_unit


def _line(
    quantity: int, is_debit: bool, unit_identifier: str = "EUR", price: int = 1
) -> JournalLine:
    return JournalLine(
        quantity=Decimal(quantity),
        unit_price=Decimal(price),
        is_debit=is_debit,
        unit=Unit(identifier=unit_identifier, name=unit_identifier, kind=UnitKind.currency),
    )


def test_multiple_units_stay_separate() -> None:
    lines = [
        _line(10, is_debit=True, unit_identifier="EUR"),
        _line(5, is_debit=True, unit_identifier="IE00B4L5Y983"),
    ]

    balances = {b.unit_identifier: b.quantity for b in _aggregate_by_unit(lines)}

    assert balances == {"EUR": Decimal(10), "IE00B4L5Y983": Decimal(5)}


def test_empty_line_list_yields_no_rows() -> None:
    assert _aggregate_by_unit([]) == []


def test_debits_minus_credits() -> None:
    lines = [
        _line(100, is_debit=True),
        _line(30, is_debit=False),
    ]

    balances = _aggregate_by_unit(lines)

    assert len(balances) == 1
    assert balances[0].quantity == Decimal(70)


def test_buy_sell_buy_uses_moving_average_not_the_rejected_readings() -> None:
    # Buy 10@100, buy 10@120, sell 5@130, buy 10@200 -> holdings 25.
    # Moving average (chosen, design §6.4) gives 146. The two rejected
    # readings on these same lines are 142 (Σ±q·p/Σ±q over all lines, sale
    # price contaminates cost basis) and 140 (debits-only, ignores that the
    # sale consumed basis). If this drifts to 142 or 140, that's a reading
    # change, not a bugfix.
    lines = [
        _line(10, is_debit=True, price=100),
        _line(10, is_debit=True, price=120),
        _line(5, is_debit=False, price=130),
        _line(10, is_debit=True, price=200),
    ]

    balances = _aggregate_by_unit(lines)

    assert len(balances) == 1
    assert balances[0].quantity == Decimal(25)
    assert balances[0].average_cost == Decimal(146)


def test_order_dependence_pins_the_service_ordering_dependency() -> None:
    # Same lines, different order, different average cost — this is what
    # makes account_lines_service's ORDER BY load-bearing rather than
    # cosmetic (design §6.4).
    lines = [
        _line(10, is_debit=True, price=100),
        _line(10, is_debit=True, price=120),
        _line(5, is_debit=False, price=130),
        _line(10, is_debit=True, price=200),
    ]
    reordered = [lines[0], lines[2], lines[1], lines[3]]

    in_order = _aggregate_by_unit(lines)[0].average_cost
    out_of_order = _aggregate_by_unit(reordered)[0].average_cost

    assert in_order == Decimal(146)
    assert out_of_order != in_order


def test_single_purchase_reports_its_own_price_as_the_average() -> None:
    lines = [_line(10, is_debit=True, price=100)]

    balances = _aggregate_by_unit(lines)

    assert len(balances) == 1
    assert balances[0].average_cost == Decimal(100)


def test_base_currency_holdings_report_average_cost_of_one() -> None:
    lines = [
        _line(200, is_debit=True, price=1),
        _line(80, is_debit=False, price=1),
    ]

    balances = _aggregate_by_unit(lines)

    assert len(balances) == 1
    assert balances[0].average_cost == Decimal(1)


def test_selling_entire_holding_takes_average_cost_to_none() -> None:
    lines = [
        _line(10, is_debit=True, price=100),
        _line(10, is_debit=False, price=130),
    ]

    balances = _aggregate_by_unit(lines)

    assert len(balances) == 1
    assert balances[0].quantity == Decimal(0)
    assert balances[0].average_cost is None


def test_quantity_going_negative_is_reported_not_rejected() -> None:
    # Base currency: unit_price is always 1, so basis and quantity stay
    # proportional and the average stays 1 however far negative it goes
    # (issue 003, envelope overspend).
    lines = [
        _line(50, is_debit=True, price=1),
        _line(200, is_debit=False, price=1),
    ]

    balances = _aggregate_by_unit(lines)

    assert len(balances) == 1
    assert balances[0].quantity == Decimal(-150)
    assert balances[0].average_cost == Decimal(1)


def test_credit_at_zero_quantity_falls_back_to_the_line_price() -> None:
    # Net-short in a non-base unit: basis/quantity is undefined at the
    # moment of the credit, so the fold falls back to that line's own price
    # rather than dividing by zero.
    lines = [_line(5, is_debit=False, unit_identifier="IE00B4L5Y983", price=90)]

    balances = _aggregate_by_unit(lines)

    assert len(balances) == 1
    assert balances[0].quantity == Decimal(-5)
    assert balances[0].average_cost == Decimal(90)


def test_account_with_no_lines_yields_no_rows() -> None:
    assert _aggregate_by_unit([]) == []


def test_two_units_in_one_account_stay_separate() -> None:
    lines = [
        _line(10, is_debit=True, unit_identifier="EUR", price=1),
        _line(5, is_debit=True, unit_identifier="IE00B4L5Y983", price=90),
    ]

    balances = {b.unit_identifier: b for b in _aggregate_by_unit(lines)}

    assert balances["EUR"].average_cost == Decimal(1)
    assert balances["IE00B4L5Y983"].average_cost == Decimal(90)
