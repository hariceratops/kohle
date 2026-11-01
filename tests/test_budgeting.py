"""Layer 1 — pure unit tests for the period builder and spending attribution.

Design §16.2. Worked examples are the spec's Testable list, with its numbers.
"""

from datetime import date
from decimal import Decimal

import pytest

from kohle.domain.models import JournalEntry, JournalLine, Unit, UnitKind
from kohle.use_cases.budgeting import (
    Cap,
    CapChange,
    CappedAccount,
    cap_periods,
    net_spent,
    period_rows,
)
from kohle.use_cases.recurrence import Yearly, parse_recurrence


def _cap(amount: str, rule: str, effective_from: date) -> CapChange:
    return CapChange(effective_from, Cap(Decimal(amount), parse_recurrence(rule).unwrap()))


def _state(_: date) -> str:
    raise AssertionError("no shifting kind here")


def _line(day: date, quantity: str, is_debit: bool = True, account_id: int = 1) -> JournalLine:
    return JournalLine(
        account_id=account_id,
        quantity=Decimal(quantity),
        unit_price=Decimal(1),
        is_debit=is_debit,
        entry=JournalEntry(entry_date=day),
        unit=Unit(identifier="EUR", name="EUR", kind=UnitKind.currency),
    )


def test_day_one_cap_yields_calendar_months() -> None:
    periods = cap_periods([_cap("300", "day 1", date(2026, 1, 1))], _state, date(2026, 3, 15))

    assert [(p.start, p.end, p.cap, p.short) for p in periods] == [
        (date(2026, 1, 1), date(2026, 1, 31), Decimal(300), False),
        (date(2026, 2, 1), date(2026, 2, 28), Decimal(300), False),
        (date(2026, 3, 1), date(2026, 3, 31), Decimal(300), False),
    ]


def test_month_end_anchor_periods_clamp_without_drifting() -> None:
    history = [_cap("10", "every 1 months from 2026-01-31", date(2026, 1, 31))]

    periods = cap_periods(history, _state, date(2026, 3, 31))

    assert [(p.start, p.end) for p in periods] == [
        (date(2026, 1, 31), date(2026, 2, 27)),
        (date(2026, 2, 28), date(2026, 3, 30)),
        (date(2026, 3, 31), date(2026, 4, 29)),
    ]


def test_a_first_period_before_the_first_occurrence_is_short() -> None:
    history = [_cap("10", "every 3 months from 2026-01-15", date(2026, 1, 1))]

    periods = cap_periods(history, _state, date(2026, 1, 20))

    assert [(p.start, p.end, p.short) for p in periods] == [
        (date(2026, 1, 1), date(2026, 1, 14), True),
        (date(2026, 1, 15), date(2026, 4, 14), False),
    ]


def test_periods_starting_after_through_are_not_generated() -> None:
    periods = cap_periods([_cap("300", "day 1", date(2026, 1, 1))], _state, date(2026, 1, 31))

    assert [p.start for p in periods] == [date(2026, 1, 1)]


def test_refund_reduces_net_spending_and_a_period_can_go_negative() -> None:
    lines = [
        _line(date(2026, 1, 3), "100"),
        _line(date(2026, 1, 9), "30", is_debit=False),
        _line(date(2026, 2, 1), "5"),
    ]

    assert net_spent(lines, date(2026, 1, 1), date(2026, 1, 31)) == Decimal(70)
    assert net_spent(lines[2:] + [_line(date(2026, 2, 2), "9", is_debit=False)], date(2026, 2, 1), date(2026, 2, 28)) == Decimal(-4)


def test_period_rows_show_whole_periods_overlapping_the_range_and_mark_today() -> None:
    capped = [CappedAccount("Groceries", [_cap("300", "day 1", date(2026, 1, 1))], frozenset({1, 2}))]
    lines = [
        _line(date(2026, 1, 31), "120"),
        _line(date(2026, 2, 1), "20", account_id=2),
        _line(date(2026, 2, 12), "310"),
        _line(date(2026, 2, 12), "999", account_id=3),
    ]

    rows = period_rows(capped, lines, _state, date(2026, 2, 5), date(2026, 2, 12), date(2026, 2, 12))

    assert [(r.period.start, r.period.end, r.spent, r.over, r.is_over, r.day) for r in rows] == [
        (date(2026, 2, 1), date(2026, 2, 28), Decimal(330), Decimal(30), True, 12),
    ]
    assert rows[0].period.days == 28


def test_each_period_stands_alone_without_rollover() -> None:
    capped = [CappedAccount("Groceries", [_cap("300", "day 1", date(2026, 1, 1))], frozenset({1}))]
    lines = [_line(date(2026, 1, 10), "100")]

    rows = period_rows(capped, lines, _state, date(2026, 1, 1), date(2026, 2, 28), date(2026, 3, 1))

    assert [(r.spent, r.over) for r in rows] == [(Decimal(100), Decimal(-200)), (Decimal(0), Decimal(-300))]


def test_yearly_period_boundary_lands_on_28_february_in_a_common_year() -> None:
    history = [CapChange(date(2027, 2, 28), Cap(Decimal(1), Yearly(2, 29)))]

    assert cap_periods(history, _state, date(2028, 3, 1))[0].end == date(2028, 2, 28)


@pytest.mark.skip(reason="TODO: slice 078 — cut at D, identical entry does not cut")
def test_placeholder_cut_at_effective_date() -> None:
    # TODO: 03-01..03-09 (short, 300) and 03-10..03-31 (short, 400), April full
    ...


@pytest.mark.skip(reason="TODO: slice 080 — covered / uncapped / unclassified split")
def test_placeholder_attribution() -> None:
    # TODO: child of capped parent counts toward the parent, not the uncapped row
    ...
