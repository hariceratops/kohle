"""Layer 1 — pure rule kinds in kohle/use_cases/recurrence.py (issues 064-067). Design §18.2."""

import calendar
import subprocess
import sys
from collections.abc import Callable
from datetime import date
from itertools import pairwise
from pathlib import Path

import pytest

from kohle.domain.domain_errors import InvalidRecurrence
from kohle.use_cases.recurrence import (
    Day,
    Every,
    LastDay,
    LastWorkday,
    NthWeekday,
    Workday,
    Yearly,
    is_working_day,
    occurrences,
    parse_recurrence,
    render_recurrence,
)

ROOT = Path(__file__).resolve().parent.parent
ALL_KINDS = (
    "one of: day N, workday N, <nth> <weekday>, last workday, last day, "
    "every N days|weeks|months from YYYY-MM-DD, yearly MM-DD"
)
EVERY_SHAPE = "every N days, weeks or months from YYYY-MM-DD"
EVERY_N = "every N … with N from 1 to 999"
EVERY_UNIT = "a unit days, weeks or months; for years write months, e.g. every 24 months"
EVERY_DATE = "a date YYYY-MM-DD after from"
YEARLY = "yearly MM-DD naming a calendar day, e.g. yearly 02-29"


def _by(_: date) -> str:
    return "BY"


@pytest.mark.parametrize(
    ("text", "canonical"),
    [
        ("day 15", "day 15"),
        ("day 5", "day 5"),
        ("day 05", "day 5"),
        ("  day   31 ", "day 31"),
        ("last workday", "last workday"),
        ("last   workday", "last workday"),
        ("workday 25", "workday 25"),
        ("workday 05", "workday 5"),
        ("last day", "last day"),
        ("last   day", "last day"),
        ("every 2 weeks from 2026-01-02", "every 2 weeks from 2026-01-02"),
        ("every 1 months from 2026-01-31", "every 1 months from 2026-01-31"),
        ("every 24 months from 2026-01-01", "every 24 months from 2026-01-01"),
        ("every 3 days from 2026-1-5", "every 3 days from 2026-01-05"),
        ("  every   03  days  from  2026-01-05 ", "every 3 days from 2026-01-05"),
        ("yearly 02-29", "yearly 02-29"),
        ("yearly 2-9", "yearly 02-09"),
        ("  yearly   12-25 ", "yearly 12-25"),
    ],
)
def test_parse_then_render_gives_the_canonical_text(text: str, canonical: str) -> None:
    rule = parse_recurrence(text).unwrap()

    assert render_recurrence(rule) == canonical
    assert parse_recurrence(canonical).unwrap() == rule


def test_parse_builds_the_kind() -> None:
    assert parse_recurrence("day 15").unwrap() == Day(15)
    assert parse_recurrence("last workday").unwrap() == LastWorkday()
    assert parse_recurrence("last day").unwrap() == LastDay()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("day 0", "day N with N from 1 to 31"),
        ("day 32", "day N with N from 1 to 31"),
        ("day x", "day N with N from 1 to 31"),
        ("day -1", "day N with N from 1 to 31"),
        ("workday 0", "workday N with N from 1 to 31"),
        ("workday 32", "workday N with N from 1 to 31"),
        ("workday x", "workday N with N from 1 to 31"),
        ("last friday", "last workday or last day; for a weekday use 1st, 2nd, 3rd or 4th"),
        ("5th fri", "an ordinal 1st, 2nd, 3rd or 4th before the weekday"),
        ("first fri", "an ordinal 1st, 2nd, 3rd or 4th before the weekday"),
        ("3rd friday", "a weekday mon, tue, wed, thu, fri, sat or sun"),
        ("3rd", ALL_KINDS),
        ("Day 15", ALL_KINDS),
        ("", ALL_KINDS),
        ("every 2 years from 2026-01-01", EVERY_UNIT),
        ("every 1 month from 2026-01-01", EVERY_UNIT),
        ("every 0 days from 2026-01-01", EVERY_N),
        ("every 1000 days from 2026-01-01", EVERY_N),
        ("every x days from 2026-01-01", EVERY_N),
        ("every 2 weeks", EVERY_SHAPE),
        ("every", EVERY_SHAPE),
        ("every 2 weeks since 2026-01-01", EVERY_SHAPE),
        ("every 2 weeks from 2026-02-30", EVERY_DATE),
        ("every 2 weeks from 20260101", EVERY_DATE),
        ("yearly 02-30", YEARLY),
        ("yearly 04-31", YEARLY),
        ("yearly 13-01", YEARLY),
        ("yearly 00-10", YEARLY),
        ("yearly 0229", YEARLY),
        ("yearly", YEARLY),
    ],
)
def test_a_bad_rule_names_the_bad_part_and_the_valid_choices(text: str, expected: str) -> None:
    err = parse_recurrence(text).unwrap_err()

    assert isinstance(err, InvalidRecurrence)
    assert err.expected == expected
    assert str(err) == f"invalid rule {text!r}; expected {expected}"


def test_day_clamps_to_the_last_day_of_the_month() -> None:
    assert occurrences(Day(31), date(2026, 2, 1), date(2026, 2, 28), _by) == [date(2026, 2, 28)]
    assert occurrences(Day(31), date(2028, 2, 1), date(2028, 2, 29), _by) == [date(2028, 2, 29)]
    assert occurrences(Day(30), date(2026, 4, 1), date(2026, 4, 30), _by) == [date(2026, 4, 30)]


def test_day_never_moves_off_a_weekend() -> None:
    assert occurrences(Day(15), date(2026, 2, 1), date(2026, 2, 28), _by) == [date(2026, 2, 15)]  # Sunday


@pytest.mark.parametrize(
    ("year", "month", "expected"),
    [
        (2026, 2, date(2026, 2, 27)),
        (2026, 10, date(2026, 10, 30)),
        (2029, 5, date(2029, 5, 30)),
        (2024, 3, date(2024, 3, 28)),
        (2026, 12, date(2026, 12, 30)),
        (2028, 12, date(2028, 12, 29)),
        (2029, 12, date(2029, 12, 28)),
    ],
)
def test_last_workday_in_bavaria(year: int, month: int, expected: date) -> None:
    last = date(year, month, calendar.monthrange(year, month)[1])

    assert occurrences(LastWorkday(), date(year, month, 1), last, _by) == [expected]


def test_the_state_in_force_on_the_unshifted_date_chooses_the_holidays() -> None:
    # Fronleichnam 2029-05-31 is a holiday in BY, not in BE.
    assert occurrences(LastWorkday(), date(2029, 5, 1), date(2029, 5, 31), lambda _: "BY") == [date(2029, 5, 30)]
    assert occurrences(LastWorkday(), date(2029, 5, 1), date(2029, 5, 31), lambda _: "BE") == [date(2029, 5, 31)]


def test_an_occurrence_after_end_is_excluded() -> None:
    assert occurrences(LastWorkday(), date(2026, 10, 1), date(2026, 10, 29), _by) == []
    assert occurrences(Day(15), date(2026, 10, 16), date(2026, 11, 14), _by) == []


def test_an_occurrence_before_start_is_excluded() -> None:
    assert occurrences(Day(15), date(2026, 3, 16), date(2026, 4, 15), _by) == [date(2026, 4, 15)]


def test_occurrences_across_years_are_ascending() -> None:
    got = occurrences(LastWorkday(), date(2025, 11, 1), date(2026, 2, 28), _by)

    assert got == [date(2025, 11, 28), date(2025, 12, 30), date(2026, 1, 30), date(2026, 2, 27)]


def test_the_state_is_asked_only_for_kinds_that_shift() -> None:
    def forbidden(_: date) -> str:
        raise AssertionError("state_on called")

    assert occurrences(Day(15), date(2026, 1, 1), date(2026, 3, 31), forbidden)


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
def test_working_day_excludes_weekends_state_holidays_and_dec_24_and_31(
    day: date, state: str, expected: bool
) -> None:
    assert is_working_day(day, state) is expected


def test_day_rules_never_import_the_holidays_package() -> None:
    code = (
        "import sys\n"
        "from datetime import date\n"
        "from kohle.use_cases.sampling import parse_sampling_rules, sample_dates\n"
        "rules = parse_sampling_rules('mid-month: day 15; salary: day 31').unwrap()\n"
        "def no_state(_):\n"
        "    raise AssertionError\n"
        "sample_dates(rules, no_state, date(2026, 1, 1), date(2026, 12, 31))\n"
        "print('holidays' in sys.modules)\n"
    )

    result = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd=ROOT, check=False
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


@pytest.mark.parametrize(("year", "month", "expected"), [(2026, 2, 28), (2028, 2, 29), (2026, 4, 30), (2026, 5, 31)])
def test_last_day_is_the_calendar_last_day_and_never_moves(year: int, month: int, expected: int) -> None:
    first, last = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])

    assert occurrences(LastDay(), first, last, _by) == [date(year, month, expected)]


def test_last_day_on_a_holiday_does_not_shift() -> None:
    assert occurrences(LastDay(), date(2026, 12, 1), date(2026, 12, 31), _by) == [date(2026, 12, 31)]


def test_last_day_never_asks_for_the_state() -> None:
    def boom(_: date) -> str:
        raise AssertionError("last day does not shift")

    assert occurrences(LastDay(), date(2026, 1, 1), date(2026, 12, 31), boom)[0] == date(2026, 1, 31)


def test_parse_builds_workday() -> None:
    assert parse_recurrence("workday 25").unwrap() == Workday(25)


def test_workday_moves_back_off_a_weekend() -> None:
    assert occurrences(Workday(15), date(2026, 2, 1), date(2026, 2, 28), _by) == [date(2026, 2, 13)]
    assert occurrences(Workday(15), date(2026, 3, 1), date(2026, 3, 31), _by) == [date(2026, 3, 13)]


def test_workday_clamps_then_shifts() -> None:
    assert occurrences(Workday(31), date(2026, 2, 1), date(2026, 2, 28), _by) == [date(2026, 2, 27)]
    assert occurrences(Workday(31), date(2028, 12, 1), date(2028, 12, 31), _by) == [date(2028, 12, 29)]


def test_workday_can_land_in_the_previous_month() -> None:
    # 1 May is a holiday and 30 April a Thursday.
    assert occurrences(Workday(1), date(2026, 4, 1), date(2026, 4, 30), _by) == [date(2026, 4, 1), date(2026, 4, 30)]


def test_parse_builds_nth_weekday() -> None:
    assert parse_recurrence("3rd fri").unwrap() == NthWeekday(3, 4)
    assert parse_recurrence("1st mon").unwrap() == NthWeekday(1, 0)


def test_nth_weekday_round_trips() -> None:
    for nth in ("1st", "2nd", "3rd", "4th"):
        for wd in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
            assert render_recurrence(parse_recurrence(f"{nth}  {wd}").unwrap()) == f"{nth} {wd}"


def test_third_friday_of_may_2026_is_the_15th() -> None:
    assert occurrences(NthWeekday(3, 4), date(2026, 5, 1), date(2026, 5, 31), _by) == [date(2026, 5, 15)]


def test_nth_weekday_on_a_holiday_moves_to_the_previous_working_day() -> None:
    assert occurrences(NthWeekday(1, 4), date(2026, 4, 1), date(2026, 4, 30), _by) == [date(2026, 4, 2), date(2026, 4, 30)]


def test_third_friday_lands_on_days_15_to_21_when_it_does_not_shift() -> None:
    found = occurrences(NthWeekday(3, 4), date(2026, 6, 1), date(2026, 6, 30), _by)

    assert found == [date(2026, 6, 19)]


def test_parse_builds_every_and_yearly() -> None:
    assert parse_recurrence("every 2 weeks from 2026-01-02").unwrap() == Every(2, "weeks", date(2026, 1, 2))
    assert parse_recurrence("yearly 02-29").unwrap() == Yearly(2, 29)


def _forbidden(_: date) -> str:
    raise AssertionError("state_on called")


def test_every_months_runs_in_both_directions_from_the_anchor() -> None:
    rule = parse_recurrence("every 3 months from 2026-01-15").unwrap()

    assert occurrences(rule, date(2025, 9, 1), date(2026, 5, 1), _forbidden) == [
        date(2025, 10, 15),
        date(2026, 1, 15),
        date(2026, 4, 15),
    ]


def test_every_months_clamps_to_the_month_without_drifting() -> None:
    rule = parse_recurrence("every 1 months from 2026-01-31").unwrap()

    assert occurrences(rule, date(2026, 1, 1), date(2026, 4, 30), _forbidden) == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
    ]


def test_yearly_feb_29_lands_on_feb_28_in_non_leap_years() -> None:
    rule = parse_recurrence("yearly 02-29").unwrap()

    assert occurrences(rule, date(2027, 1, 1), date(2028, 12, 31), _forbidden) == [
        date(2027, 2, 28),
        date(2028, 2, 29),
    ]


def test_every_days_keeps_the_phase_before_and_after_the_anchor() -> None:
    rule = parse_recurrence("every 3 days from 2026-01-10").unwrap()

    assert occurrences(rule, date(2026, 1, 5), date(2026, 1, 12), _forbidden) == [date(2026, 1, 7), date(2026, 1, 10)]


def test_every_weeks_are_fourteen_days_apart_on_the_anchor_weekday() -> None:
    rule = parse_recurrence("every 2 weeks from 2026-01-02").unwrap()

    found = occurrences(rule, date(2025, 11, 1), date(2026, 3, 1), _forbidden)

    assert date(2026, 1, 2) in found
    assert all(d.weekday() == 4 for d in found)
    assert all((b - a).days == 14 for a, b in pairwise(found))
    assert found[0] < date(2026, 1, 2) < found[-1]


def test_the_start_and_end_are_inclusive_for_every_and_yearly() -> None:
    rule = parse_recurrence("every 2 weeks from 2026-01-02").unwrap()
    assert occurrences(rule, date(2026, 1, 2), date(2026, 1, 16), _forbidden) == [date(2026, 1, 2), date(2026, 1, 16)]
    assert occurrences(Yearly(12, 25), date(2026, 12, 25), date(2026, 12, 25), _forbidden) == [date(2026, 12, 25)]


@pytest.mark.parametrize("text", ["every 1 days from 2026-01-01", "yearly 12-25"])
def test_every_and_yearly_never_shift_to_a_working_day(text: str) -> None:
    rule = parse_recurrence(text).unwrap()

    found = occurrences(rule, date(2026, 12, 24), date(2026, 12, 26), _forbidden)

    assert date(2026, 12, 25) in found
    if text.startswith("every"):
        assert found == [date(2026, 12, 24), date(2026, 12, 25), date(2026, 12, 26)]


def test_every_and_yearly_never_import_the_holidays_package() -> None:
    code = (
        "import sys\n"
        "from datetime import date\n"
        "from kohle.use_cases.sampling import parse_sampling_rules, sample_dates\n"
        "rules = parse_sampling_rules("
        "'mid-month: every 2 weeks from 2026-01-02; salary: yearly 02-29').unwrap()\n"
        "def no_state(_):\n"
        "    raise AssertionError\n"
        "sample_dates(rules, no_state, date(2026, 1, 1), date(2026, 12, 31))\n"
        "print('holidays' in sys.modules)\n"
    )

    result = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd=ROOT, check=False
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def _history_state(history: str) -> Callable[[date], str]:
    if history == "BY":
        return _by
    return lambda day: "NI" if day >= date(2026, 1, 1) else "BY"


def test_the_month_based_kinds_equal_the_pre_rewrite_oracle() -> None:
    lines = (ROOT / "tests" / "fixtures" / "occurrences_monthly_kinds.txt").read_text().splitlines()
    assert len(lines) == 72

    for line in lines:
        history, text, dates = (part.strip() for part in line.split(" | "))
        rule = parse_recurrence(text).unwrap()

        found = occurrences(rule, date(2000, 1, 1), date(2040, 12, 31), _history_state(history))

        assert " ".join(d.isoformat() for d in found) == dates, (history, text)
