"""Layer 1 — pure unit tests, no fixture.

The pass that snapshots the moving-average fold at each sample date, and the
Bundesland codes. Sample-date and working-day cases live in test_recurrence.py
and test_sampling_rules.py (design §18).
"""

from datetime import date
from decimal import Decimal

import pytest

from kohle.domain.models import JournalEntry, JournalLine, Unit, UnitKind
from kohle.use_cases.bundesland import STATES
from kohle.use_cases.journal import aggregate_by_unit, aggregate_by_unit_through


@pytest.mark.parametrize("state", STATES)
def test_holidays_package_accepts_all_sixteen_state_codes(state):
    import holidays

    holidays.country_holidays("DE", subdiv=state)


def test_augsburg_is_not_a_state():
    assert "Augsburg" not in STATES and len(STATES) == 16


def _line(entry_date: date, quantity: int, is_debit: bool, identifier: str = "EUR", price: int = 1) -> JournalLine:
    kind = UnitKind.currency if identifier == "EUR" else UnitKind.security
    return JournalLine(
        quantity=Decimal(quantity),
        unit_price=Decimal(price),
        is_debit=is_debit,
        entry=JournalEntry(entry_date=entry_date),
        unit=Unit(identifier=identifier, name=identifier, kind=kind),
    )


def test_snapshot_per_date_equals_aggregate_by_unit_of_the_prefix():
    lines = [
        _line(date(2026, 1, 5), 1000, True),
        _line(date(2026, 1, 15), 10, True, "X1", 100),
        _line(date(2026, 1, 15), 4, False, "X1", 130),
        _line(date(2026, 2, 1), 10, True, "X1", 120),
        _line(date(2026, 2, 20), 300, False),
    ]
    dates = [date(2026, 1, 14), date(2026, 1, 15), date(2026, 1, 31), date(2026, 2, 20), date(2026, 3, 1)]

    snapshots = aggregate_by_unit_through(lines, dates)

    assert snapshots == [
        aggregate_by_unit([ln for ln in lines if ln.entry.entry_date <= day]) for day in dates
    ]


def test_snapshot_before_the_first_line_is_empty():
    lines = [_line(date(2026, 1, 5), 1000, True)]

    assert aggregate_by_unit_through(lines, [date(2026, 1, 4)]) == [[]]
