"""Flow and budget calculations from meter readings."""

from __future__ import annotations

import calendar
from datetime import datetime

from .const import NIGHT_END_HOUR, NIGHT_MIN_HOURS, NIGHT_START_HOUR


def _in_night(when: datetime) -> bool:
    return when.hour >= NIGHT_START_HOUR or when.hour < NIGHT_END_HOUR


def night_flow(
    start: tuple[datetime, float], end: tuple[datetime, float]
) -> float | None:
    """Return the average flow in litres per hour between two readings.

    Only readings that both fall in the night window, less than a night apart
    and at least a couple of hours apart, are judged; otherwise None.
    """
    (t0, v0), (t1, v1) = start, end
    hours = (t1 - t0).total_seconds() / 3600
    if hours < NIGHT_MIN_HOURS or hours > 24 - (NIGHT_START_HOUR - NIGHT_END_HOUR):
        return None
    if not (_in_night(t0) and _in_night(t1)) or v1 < v0:
        return None
    return round((v1 - v0) * 1000 / hours, 2)


def project_month(consumption: float, now: datetime) -> float | None:
    """Project the month's consumption from the use so far."""
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elapsed_days = (now - start).total_seconds() / 86400
    if elapsed_days < 1:
        return None
    days = calendar.monthrange(now.year, now.month)[1]
    return round(consumption / elapsed_days * days, 3)
