"""The one recurrence vocabulary: rule kinds, their text form, and the dates
they land on (design §3, §7.1). Pure: no storage, no roles, no prices."""

import calendar
import functools
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import takewhile
from typing import TYPE_CHECKING, Literal, assert_never

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


@dataclass(frozen=True, slots=True)
class Every:
    n: int
    unit: Literal["days", "weeks", "months"]
    anchor: date  # fixes the phase only


@dataclass(frozen=True, slots=True)
class Yearly:
    month: int
    day: int


Monthly = Day | Workday | NthWeekday | LastWorkday | LastDay
Recurrence = Monthly | Every | Yearly

KINDS = (
    "day N",
    "workday N",
    "<nth> <weekday>",
    "last workday",
    "last day",
    "every N days|weeks|months from YYYY-MM-DD",
    "yearly MM-DD",
)

_UNITS = ("days", "weeks", "months")
_MAX_N = 999

_ORDINALS = ("1st", "2nd", "3rd", "4th")
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def parse_recurrence(text: str) -> Result[Recurrence, InvalidRecurrence]:
    match text.split():
        case ["every", *rest]:
            return _parse_every(text, rest)
        case ["yearly", *rest]:
            return _parse_yearly(text, rest)
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


def _parse_every(text: str, rest: list[str]) -> Result[Recurrence, InvalidRecurrence]:
    if len(rest) != 4 or rest[2] != "from":
        return Result.err(InvalidRecurrence(text, "every N days, weeks or months from YYYY-MM-DD"))
    n, unit, _, anchor = rest
    if not (n.isascii() and n.isdigit() and 1 <= int(n) <= _MAX_N):
        return Result.err(InvalidRecurrence(text, f"every N … with N from 1 to {_MAX_N}"))
    if unit not in _UNITS:
        return Result.err(
            InvalidRecurrence(text, "a unit days, weeks or months; for years write months, e.g. every 24 months")
        )
    try:
        anchor_date = datetime.strptime(anchor, "%Y-%m-%d").date()  # noqa: DTZ007
    except ValueError:
        return Result.err(InvalidRecurrence(text, "a date YYYY-MM-DD after from"))
    return Result.ok(Every(int(n), unit, anchor_date))  # type: ignore[arg-type]


def _parse_yearly(text: str, rest: list[str]) -> Result[Recurrence, InvalidRecurrence]:
    error = InvalidRecurrence(text, "yearly MM-DD naming a calendar day, e.g. yearly 02-29")
    if len(rest) != 1:
        return Result.err(error)
    parts = rest[0].split("-")
    if len(parts) != 2 or not all(p.isascii() and p.isdigit() and len(p) <= 2 for p in parts):
        return Result.err(error)
    month, day = int(parts[0]), int(parts[1])
    # 2024 is a leap year, so 02-29 is a valid day.
    if not 1 <= month <= 12 or not 1 <= day <= calendar.monthrange(2024, month)[1]:
        return Result.err(error)
    return Result.ok(Yearly(month, day))


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
        case Every(n, unit, anchor):
            return f"every {n} {unit} from {anchor.isoformat()}"
        case Yearly(month, day):
            return f"yearly {month:02d}-{day:02d}"
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


def _unshifted(rule: Monthly, year: int, month: int) -> date:
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
        case Day() | LastDay() | Every() | Yearly():
            return False
        case Workday() | NthWeekday() | LastWorkday():
            return True
        case _:
            assert_never(rule)


def _month_index(day: date) -> int:
    return 12 * day.year + day.month - 1


def _clamped(index: int, day: int) -> date:
    year, month0 = divmod(index, 12)
    return date(year, month0 + 1, min(day, calendar.monthrange(year, month0 + 1)[1]))


def _ascending(rule: Recurrence, start: date, state_on: Callable[[date], str]) -> Iterator[date]:
    """Every date the rule lands on from `start` onward, ascending, without end.
    The month-based kinds are strictly ascending after their backward shift:
    unshifted dates are at least 28 days apart and a shift is at most 5 days."""
    match rule:
        case Every(n, "days" | "weeks" as unit, anchor):
            step = n if unit == "days" else 7 * n
            ordinal = anchor.toordinal() - ((anchor.toordinal() - start.toordinal()) // step) * step
            while True:
                yield date.fromordinal(ordinal)
                ordinal += step
        case Every(n, _, anchor):
            k = (_month_index(start) - _month_index(anchor)) // n
            while True:
                day = _clamped(_month_index(anchor) + k * n, anchor.day)
                if day >= start:
                    yield day
                k += 1
        case Yearly(month, day):
            year = start.year
            while True:
                last = calendar.monthrange(year, month)[1]
                found = date(year, month, min(day, last))
                if found >= start:
                    yield found
                year += 1
        case Day() | Workday() | NthWeekday() | LastWorkday() | LastDay():
            year, month = start.year, start.month
            while True:
                found = _unshifted(rule, year, month)
                if _shifts(rule):
                    state = state_on(found)
                    while not is_working_day(found, state):
                        found -= timedelta(days=1)
                if found >= start:
                    yield found
                year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        case _:
            assert_never(rule)


def occurrences(
    rule: Recurrence, start: date, end: date, state_on: Callable[[date], str]
) -> list[date]:
    """Every date the rule lands on in [start, end], ascending. The shifting
    kinds move each unshifted date back to a working day under the state in
    force on that unshifted date. The shift loop has no guard: a real calendar
    has a working day within days."""
    return list(takewhile(lambda day: day <= end, _ascending(rule, start, state_on)))


def next_occurrence(rule: Recurrence, after: date, state_on: Callable[[date], str]) -> date:
    """The first date the rule lands on strictly after `after`."""
    return next(_ascending(rule, after + timedelta(days=1), state_on))
