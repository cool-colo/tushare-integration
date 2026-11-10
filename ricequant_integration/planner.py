from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Iterator


@dataclass(frozen=True)
class DateSlice:
    start: date
    end: date
    slice_key: str


def month_slices(start: date, end: date, prefix: str = "") -> Iterator[DateSlice]:
    cursor = start.replace(day=1)
    while cursor <= end:
        month_end = date(
            cursor.year, cursor.month, calendar.monthrange(cursor.year, cursor.month)[1]
        )
        slice_start = max(start, cursor)
        slice_end = min(end, month_end)
        yield DateSlice(slice_start, slice_end, f"{prefix}{cursor:%Y-%m}")
        cursor = month_end + timedelta(days=1)


def daily_slices(dates: Iterable[date], prefix: str = "") -> Iterator[DateSlice]:
    for value in sorted(set(dates)):
        yield DateSlice(value, value, f"{prefix}{value:%Y-%m-%d}")


def month_end_trading_dates(trading_dates: Iterable[date]) -> list[date]:
    result: dict[tuple[int, int], date] = {}
    for value in sorted(set(trading_dates)):
        result[(value.year, value.month)] = value
    return list(result.values())


def incremental_start(
    last_completed: date | None, first_allowed: date, rescan_days: int = 0
) -> date:
    if last_completed is None:
        return first_allowed
    return max(
        first_allowed, last_completed + timedelta(days=1) - timedelta(days=rescan_days)
    )


def report_periods_to_rescan(
    today: date, mutable_days: int, quarter_months: tuple[int, ...] = (3, 6, 9, 12)
) -> list[date]:
    """Plan mutable financial periods without inventing a trading date."""
    cutoff = today - timedelta(days=mutable_days)
    result: list[date] = []
    for year in range(cutoff.year - 1, today.year + 1):
        for month in quarter_months:
            value = date(year, month, calendar.monthrange(year, month)[1])
            if cutoff <= value <= today:
                result.append(value)
    return result


def quarter_end_on_or_before(value: date) -> date:
    quarter = (value.month - 1) // 3 + 1
    month = quarter * 3
    candidate = date(value.year, month, calendar.monthrange(value.year, month)[1])
    if candidate <= value:
        return candidate
    previous_month = month - 3
    if previous_month:
        return date(
            value.year,
            previous_month,
            calendar.monthrange(value.year, previous_month)[1],
        )
    return date(value.year - 1, 12, 31)


def quarter_end_on_or_after(value: date) -> date:
    quarter = (value.month - 1) // 3 + 1
    month = quarter * 3
    return date(value.year, month, calendar.monthrange(value.year, month)[1])


def quarter_label(value: date) -> str:
    if value.month not in {3, 6, 9, 12} or value.day != calendar.monthrange(
        value.year, value.month
    )[1]:
        raise ValueError(f"not a quarter end: {value}")
    return f"{value.year}q{value.month // 3}"
