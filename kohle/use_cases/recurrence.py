"""The one recurrence vocabulary: rule kinds, their text form, and the dates
they land on (design §3, §7.1). Pure: no storage, no roles, no prices."""

import calendar
import functools
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, assert_never

from kohle.core.result import Result
from kohle.domain.domain_errors import InvalidRecurrence

if TYPE_CHECKING:
    import holidays


@dataclass(frozen=True, slots=True)
class Day:
    day: int


@dataclass(frozen=True, slots=True)
class Workday:
    day: int


@dataclass(frozen=True, slots=True)
class NthWeekday:
    nth: int
    weekday: int


@dataclass(frozen=True, slots=True)
class LastWorkday:
    pass


@dataclass(frozen=True, slots=True)
class LastDay:
    pass


Recurrence = Day | Workday | NthWeekday | LastWorkday | LastDay

KINDS = ("day N", "workday N", "<nth> <weekday>", "last workday", "last day")

_ORDINALS = ("1st", "2nd", "3rd", "4th")
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def parse_recurrence(text: str) -> Result[Recurrence, InvalidRecurrence]:
    match text.split():
        case ["day", n]:
            if n.isascii() and n.isdigit() and 1 <= int(n) <= 31:
                return Result.ok(Day(int(n)))
            return Result.err(InvalidRecurrence(text, "day N with N from 1 to 31"))
        case ["workday", n]:
            if n.isascii() and n.isdigit() and 1 <= int(n) <= 31:
                return Result.ok(Workday(int(n)))
            return Result.err(InvalidRecurrence(text, "workday N with N from 1 to 31"))
        case ["last", "workday"]:
            return Result.ok(LastWorkday())
        case ["last", "day"]:
            return Result.ok(LastDay())
        case ["last", *_]:
            return Result.err(
                InvalidRecurrence(text, "last workday or last day; for a weekday use 1st, 2nd, 3rd or 4th")
            )
        case [nth, weekday] if nth in _ORDINALS and weekday in _WEEKDAYS:
            return Result.ok(NthWeekday(_ORDINALS.index(nth) + 1, _WEEKDAYS.index(weekday)))
        case [nth, _] if nth in _ORDINALS:
            return Result.err(InvalidRecurrence(text, "a weekday mon, tue, wed, thu, fri, sat or sun"))
        case [_, weekday] if weekday in _WEEKDAYS:
            return Result.err(InvalidRecurrence(text, "an ordinal 1st, 2nd, 3rd or 4th before the weekday"))
        case _:
            return Result.err(InvalidRecurrence(text, f"one of: {', '.join(KINDS)}"))


def render_recurrence(rule: Recurrence) -> str:
    match rule:
        case Day(day):
            return f"day {day}"
        case Workday(day):
            return f"workday {day}"
        case NthWeekday(nth, weekday):
            return f"{_ORDINALS[nth - 1]} {_WEEKDAYS[weekday]}"
        case LastWorkday():
            return "last workday"
        case LastDay():
            return "last day"
        case _:
            assert_never(rule)


@functools.cache
def _public_holidays(state: str) -> "holidays.HolidayBase":
    # Imported here: it costs ~0.19 s, which every other command would pay.
    import holidays

    return holidays.country_holidays("DE", subdiv=state)


def is_working_day(day: date, state: str) -> bool:
    return (
        day.weekday() < 5
        and day not in _public_holidays(state)
        and (day.month, day.day) not in {(12, 24), (12, 31)}
    )


def _unshifted(rule: Recurrence, year: int, month: int) -> date:
    last = calendar.monthrange(year, month)[1]
    match rule:
        case Day(day) | Workday(day):
            return date(year, month, min(day, last))
        case NthWeekday(nth, weekday):
            first_weekday = calendar.weekday(year, month, 1)
            return date(year, month, 1 + (weekday - first_weekday) % 7 + 7 * (nth - 1))
        case LastWorkday() | LastDay():
            return date(year, month, last)
        case _:
            assert_never(rule)


def _shifts(rule: Recurrence) -> bool:
    match rule:
        case Day() | LastDay():
            return False
        case Workday() | NthWeekday() | LastWorkday():
            return True
        case _:
            assert_never(rule)


def occurrences(
    rule: Recurrence, start: date, end: date, state_on: Callable[[date], str]
) -> list[date]:
    """Every date the rule lands on in [start, end], ascending: each unshifted
    date, moved back to a working day under the state in force on that
    unshifted date when the kind shifts. The month after `end`'s is walked
    too, because a shift moves backward and can land inside the range. The
    shift loop has no guard: a real calendar has a working day within days."""
    found: list[date] = []
    year, month = start.year, start.month
    through = (end.year + 1, 1) if end.month == 12 else (end.year, end.month + 1)
    while (year, month) <= through:
        day = _unshifted(rule, year, month)
        if _shifts(rule):
            state = state_on(day)
            while not is_working_day(day, state):
                day -= timedelta(days=1)
        if start <= day <= end:
            found.append(day)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return sorted(found)
