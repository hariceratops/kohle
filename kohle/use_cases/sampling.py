"""The dates `net-worth-history` samples (design §6)."""

import calendar
from collections.abc import Callable
from datetime import date, timedelta


def period_end(year: int, month: int, counts: Callable[[date], bool]) -> date:
    """The last day of the month for which `counts` holds. The loop has no
    guard: a real calendar always has a counting day in a month's last 16."""
    day = date(year, month, calendar.monthrange(year, month)[1])
    while not counts(day):
        day -= timedelta(days=1)
    return day


def sample_dates(start: date, end: date) -> list[date]:
    """The 15th and the calendar month-end of each month in `[start, end]`,
    then `end` itself unless it is already the last date."""
    dates: list[date] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        for day in (date(year, month, 15), period_end(year, month, lambda _: True)):
            if start <= day <= end:
                dates.append(day)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    if not dates or dates[-1] != end:
        dates.append(end)
    return dates
