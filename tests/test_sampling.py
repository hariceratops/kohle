"""Layer 1 — pure unit tests, no fixture.

`period_end` and `sample_dates` (issue 045), and the pass that snapshots the
moving-average fold at each sample date. The working-day cases are issue 046.
"""

from datetime import date
from decimal import Decimal

import pytest

from kohle.domain.models import JournalEntry, JournalLine, Unit, UnitKind
from kohle.use_cases.journal import aggregate_by_unit, aggregate_by_unit_through
from kohle.use_cases.sampling import (
    STATES,
    PeriodEnd,
    period_end,
    sample_dates,
    working_days,
)


def test_period_end_with_an_always_true_predicate_is_the_calendar_last_day():
    assert period_end(2026, 2, lambda _: True) == date(2026, 2, 28)
    assert period_end(2028, 2, lambda _: True) == date(2028, 2, 29)


def test_period_end_steps_back_over_days_the_predicate_rejects():
    assert period_end(2026, 10, lambda day: day.day <= 29) == date(2026, 10, 29)
    assert period_end(2026, 10, lambda day: day.day <= 29 and day != date(2026, 10, 29)) == date(2026, 10, 28)


def test_sample_dates_are_the_15th_and_month_end_plus_final_row_at_to():
    dates = sample_dates(date(2025, 12, 1), date(2026, 2, 20))

    assert dates == [
        date(2025, 12, 15), date(2025, 12, 31),
        date(2026, 1, 15), date(2026, 1, 31),
        date(2026, 2, 15), date(2026, 2, 20),
    ]


@pytest.mark.parametrize("end", [date(2026, 3, 15), date(2026, 3, 31)])
def test_sample_dates_append_nothing_when_to_is_already_a_sample_date(end):
    dates = sample_dates(date(2026, 3, 1), end)

    assert dates[-1] == end
    assert dates.count(end) == 1


def test_sample_dates_drop_the_15th_before_start():
    assert sample_dates(date(2026, 3, 16), date(2026, 4, 15)) == [
        date(2026, 3, 31), date(2026, 4, 15),
    ]


def test_sample_dates_with_start_equal_to_end_is_one_row():
    assert sample_dates(date(2026, 3, 12), date(2026, 3, 12)) == [date(2026, 3, 12)]


BY_SATURDAY = date(2026, 10, 31)


@pytest.mark.parametrize(
    ("day", "state", "expected"),
    [
        (date(2026, 10, 30), "BY", True),
        (date(2026, 10, 31), "BY", False),  # Saturday
        (date(2026, 11, 1), "BY", False),  # Sunday, and All Saints in BY
        (date(2029, 5, 31), "BY", False),  # Fronleichnam
        (date(2029, 5, 31), "BE", True),
        (date(2024, 3, 29), "BY", False),  # Karfreitag
        (date(2026, 12, 24), "BY", False),
        (date(2026, 12, 31), "BY", False),
        (date(2026, 12, 30), "BY", True),
    ],
)
def test_working_day_excludes_weekends_state_holidays_and_dec_24_and_31(day, state, expected):
    assert working_days(state)(day) is expected


@pytest.mark.parametrize(
    ("year", "month", "expected"),
    [
        (2026, 10, date(2026, 10, 30)),
        (2029, 5, date(2029, 5, 30)),
        (2024, 3, date(2024, 3, 28)),
        (2026, 12, date(2026, 12, 30)),
        (2028, 12, date(2028, 12, 29)),
        (2029, 12, date(2029, 12, 28)),
    ],
)
def test_last_working_day_period_end_in_bavaria(year, month, expected):
    assert period_end(year, month, working_days("BY")) == expected


def test_state_changes_the_period_end():
    assert period_end(2029, 5, working_days("BE")) == date(2029, 5, 31)


def test_sample_dates_last_working_day_moves_the_period_end_not_the_15th():
    dates = sample_dates(date(2026, 10, 1), date(2026, 10, 31), PeriodEnd.last_working_day, "BY")

    assert dates == [date(2026, 10, 15), date(2026, 10, 30), date(2026, 10, 31)]


def test_sample_dates_month_end_ignores_the_state():
    assert sample_dates(date(2026, 10, 1), date(2026, 10, 31), PeriodEnd.month_end, "BY") == [
        date(2026, 10, 15), date(2026, 10, 31),
    ]


def test_sample_dates_never_include_dec_24_or_31():
    dates = sample_dates(date(2028, 12, 1), date(2028, 12, 29), PeriodEnd.last_working_day, "BY")

    assert dates == [date(2028, 12, 15), date(2028, 12, 29)]
    assert not {date(2028, 12, 24), date(2028, 12, 31)} & set(
        sample_dates(date(2020, 1, 1), date(2030, 1, 1), PeriodEnd.last_working_day, "BY")
    )


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
