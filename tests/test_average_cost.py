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


def _line(quantity: int, is_debit: bool, unit_identifier: str = "EUR") -> JournalLine:
    return JournalLine(
        quantity=Decimal(quantity),
        unit_price=Decimal(1),
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


# TODO: buy 10@100, buy 10@120, sell 5@130, buy 10@200 -> avg cost 146
#       (the rejected readings give 142 and 140 on the same lines)
# TODO: a single purchase reports its own price as the average
# TODO: base-currency holdings report an average cost of 1
# TODO: selling the entire holding takes quantity to exactly zero
#       without dividing by zero
# TODO: quantity going negative (oversold) is reported, not rejected
# TODO: an account with no lines yields no rows rather than an error
# TODO: two units in one account stay separate, never combined
