"""Layer 1 — pure rule kinds in kohle/use_cases/recurrence.py (issues 064-067). Design §18.2."""

import calendar
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from kohle.domain.domain_errors import InvalidRecurrence
from kohle.use_cases.recurrence import (
    Day,
    LastWorkday,
    is_working_day,
    occurrences,
    parse_recurrence,
    render_recurrence,
)

ROOT = Path(__file__).resolve().parent.parent


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
    ],
)
def test_parse_then_render_gives_the_canonical_text(text: str, canonical: str) -> None:
    rule = parse_recurrence(text).unwrap()

    assert render_recurrence(rule) == canonical
    assert parse_recurrence(canonical).unwrap() == rule


def test_parse_builds_the_kind() -> None:
    assert parse_recurrence("day 15").unwrap() == Day(15)
    assert parse_recurrence("last workday").unwrap() == LastWorkday()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("day 0", "day N with N from 1 to 31"),
        ("day 32", "day N with N from 1 to 31"),
        ("day x", "day N with N from 1 to 31"),
        ("day -1", "day N with N from 1 to 31"),
        ("last friday", "last workday"),
        ("Day 15", "one of: day N, last workday"),
        ("every 2 weeks from 2026-01-02", "one of: day N, last workday"),
        ("yearly 12-24", "one of: day N, last workday"),
        ("", "one of: day N, last workday"),
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
