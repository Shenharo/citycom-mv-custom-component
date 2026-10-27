"""Import daily consumption history as long-term statistics."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.const import UnitOfVolume
from homeassistant.helpers.recorder import DATA_INSTANCE
from homeassistant.util import dt as dt_util

from .const import DOMAIN

if TYPE_CHECKING:
    from citycom_mv_api.models.ConsumptionTimeSeries import ConsumptionTimeSeries
    from homeassistant.core import HomeAssistant


def statistic_id(meter_id: int) -> str:
    """External statistic id of a meter."""
    return f"{DOMAIN}:meter_{meter_id}_consumption"


def daily_totals(series: ConsumptionTimeSeries) -> dict[date, float]:
    """Sum the series per calendar day (the API may split a day into hours)."""
    totals: dict[date, float] = defaultdict(float)
    for when, value in series.get_sorted_data():
        if value is not None:
            totals[when.date() if isinstance(when, datetime) else when] += value
    return dict(sorted(totals.items()))


def build_statistics(
    totals: dict[date, float], last_reading: float
) -> list[StatisticData]:
    """Build cumulative statistics that equal the meter reading.

    Working back from the current reading keeps every import idempotent, so
    re-importing an overlapping window rewrites the same values.
    """
    stats: list[StatisticData] = []
    running = last_reading
    for day, value in reversed(list(totals.items())):
        start = dt_util.as_utc(
            datetime.combine(day, time.min, tzinfo=dt_util.get_default_time_zone())
        )
        stats.append(StatisticData(start=start, state=running, sum=running))
        running -= value
    stats.reverse()
    return stats


def import_history(
    hass: HomeAssistant,
    meter_id: int,
    name: str,
    series: ConsumptionTimeSeries,
    last_reading: float | None,
) -> None:
    """Write a meter's daily history as external statistics."""
    if DATA_INSTANCE not in hass.data:
        return  # recorder not running
    totals = daily_totals(series)
    if not totals or last_reading is None:
        return
    metadata = StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=name,
        source=DOMAIN,
        statistic_id=statistic_id(meter_id),
        unit_class="volume",
        unit_of_measurement=UnitOfVolume.CUBIC_METERS,
    )
    async_add_external_statistics(
        hass, metadata, build_statistics(totals, last_reading)
    )
