"""The dates `net-worth-history` samples (design §6)."""

import calendar
from collections.abc import Callable
from datetime import date, timedelta
from enum import Enum


class PeriodEnd(Enum):
    month_end = "month-end"
    last_working_day = "last-working-day"


# Written out because `holidays.Germany.subdivisions` also lists "Augsburg",
# a city, which is not a Bundesland.
STATES = (
    "BB", "BE", "BW", "BY", "HB", "HE", "HH", "MV",
    "NI", "NW", "RP", "SH", "SL", "SN", "ST", "TH",
)


def working_days(state: str) -> Callable[[date], bool]:
    # Imported here: it costs ~0.19 s, which every other command would pay.
    import holidays

    public = holidays.country_holidays("DE", subdiv=state)
    return lambda day: (
        day.weekday() < 5 and day not in public and (day.month, day.day) not in {(12, 24), (12, 31)}
    )


def period_end(year: int, month: int, counts: Callable[[date], bool]) -> date:
    """The last day of the month for which `counts` holds. The loop has no
    guard: a real calendar always has a counting day in a month's last 16."""
    day = date(year, month, calendar.monthrange(year, month)[1])
    while not counts(day):
        day -= timedelta(days=1)
    return day


def sample_dates(
    start: date, end: date, mode: PeriodEnd = PeriodEnd.month_end, state: str = "BY"
) -> list[date]:
    """The 15th and the period end of each month in `[start, end]`, then `end`
    itself unless it is already the last date. `state` only matters under
    `last_working_day`."""
    counts = (lambda _: True) if mode is PeriodEnd.month_end else working_days(state)
    dates: list[date] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        for day in (date(year, month, 15), period_end(year, month, counts)):
            if start <= day <= end:
                dates.append(day)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    if not dates or dates[-1] != end:
        dates.append(end)
    return dates
