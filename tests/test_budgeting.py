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


def test_workday_25_runs_payday_to_payday_under_the_state_in_force() -> None:
    history = [_cap("10", "workday 25", date(2025, 9, 25))]

    periods = cap_periods(history, lambda _: "BY", date(2025, 12, 31))

    assert [(p.start, p.end, p.short) for p in periods] == [
        (date(2025, 9, 25), date(2025, 10, 23), False),
        (date(2025, 10, 24), date(2025, 11, 24), False),
        (date(2025, 11, 25), date(2025, 12, 22), False),
        (date(2025, 12, 23), date(2026, 1, 22), False),
    ]


def test_every_periods_never_shift_to_a_working_day() -> None:
    history = [_cap("10", "every 1 weeks from 2026-01-03", date(2026, 1, 3))]

    periods = cap_periods(history, _state, date(2026, 1, 10))

    assert [(p.start, p.end) for p in periods] == [
        (date(2026, 1, 3), date(2026, 1, 9)),
        (date(2026, 1, 10), date(2026, 1, 16)),
    ]


def test_a_new_cap_cuts_the_running_period_the_day_before_it_and_is_not_prorated() -> None:
    history = [_cap("300", "day 1", date(2026, 1, 1)), _cap("400", "day 1", date(2026, 3, 10))]

    periods = cap_periods(history, _state, date(2026, 4, 30))

    assert [(p.start, p.end, p.cap, p.short) for p in periods[2:]] == [
        (date(2026, 3, 1), date(2026, 3, 9), Decimal(300), True),
        (date(2026, 3, 10), date(2026, 3, 31), Decimal(400), True),
        (date(2026, 4, 1), date(2026, 4, 30), Decimal(400), False),
    ]


def test_an_entry_identical_to_the_one_in_force_does_not_cut() -> None:
    history = [_cap("300", "day 1", date(2026, 1, 1)), _cap("300", "day 1", date(2026, 1, 20))]

    periods = cap_periods(history, _state, date(2026, 2, 28))

    assert [(p.start, p.end, p.short) for p in periods] == [
        (date(2026, 1, 1), date(2026, 1, 31), False),
        (date(2026, 2, 1), date(2026, 2, 28), False),
    ]


def test_an_end_entry_leaves_no_periods_and_cuts_the_running_one() -> None:
    cap = _cap("300", "day 1", date(2026, 1, 1))

    at_boundary = cap_periods([cap, CapChange(date(2026, 4, 1), None)], _state, date(2026, 6, 30))
    mid_period = cap_periods([cap, CapChange(date(2026, 4, 10), None)], _state, date(2026, 6, 30))

    assert [(p.start, p.end, p.short) for p in at_boundary] == [
        (date(2026, 1, 1), date(2026, 1, 31), False),
        (date(2026, 2, 1), date(2026, 2, 28), False),
        (date(2026, 3, 1), date(2026, 3, 31), False),
    ]
    assert [(p.start, p.end, p.short) for p in mid_period][-1] == (date(2026, 4, 1), date(2026, 4, 9), True)
    assert len(mid_period) == 4


def test_a_cap_set_again_after_an_end_entry_starts_fresh() -> None:
    history = [
        _cap("300", "day 1", date(2026, 1, 1)),
        CapChange(date(2026, 2, 1), None),
        _cap("300", "day 1", date(2026, 3, 15)),
    ]

    periods = cap_periods(history, _state, date(2026, 4, 30))

    assert [(p.start, p.end, p.short) for p in periods] == [
        (date(2026, 1, 1), date(2026, 1, 31), False),
        (date(2026, 3, 15), date(2026, 3, 31), True),
        (date(2026, 4, 1), date(2026, 4, 30), False),
    ]


@pytest.mark.skip(reason="TODO: slice 080 — covered / uncapped / unclassified split")
def test_placeholder_attribution() -> None:
    # TODO: child of capped parent counts toward the parent, not the uncapped row
    ...
