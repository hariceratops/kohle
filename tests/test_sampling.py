"""Layer 1 — pure unit tests, no fixture.

`period_end` and `sample_dates` (issue 045), and the pass that snapshots the
moving-average fold at each sample date. The working-day cases are issue 046.
"""

from datetime import date
from decimal import Decimal

import pytest

from kohle.domain.models import JournalEntry, JournalLine, Unit, UnitKind
from kohle.use_cases.journal import aggregate_by_unit, aggregate_by_unit_through
from kohle.use_cases.sampling import period_end, sample_dates


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


@pytest.mark.skip(reason="issue 046")
def test_working_day_excludes_weekends_state_holidays_and_dec_24_and_31():
    # TODO(046): Bavaria vs Berlin on 2029-05-31; December 2028 lands on 29 Dec
    ...


@pytest.mark.skip(reason="issue 046")
def test_holidays_package_accepts_all_sixteen_state_codes():
    # TODO(046)
    ...


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
