"""Sensor platform for citycom_mv_water_meter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfVolume
from homeassistant.util import dt as dt_util

from .entity import CitycomMeterEntity

if TYPE_CHECKING:
    from citycom_mv_api.models.Reading import MeterReadings
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import CitycomConfigEntry


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=dt_util.get_default_time_zone())


@dataclass(frozen=True, kw_only=True)
class CitycomSensorEntityDescription(SensorEntityDescription):
    """Describes a Citycom meter sensor."""

    value_fn: Callable[[MeterReadings], Any]
    # Name of a coordinator dict, keyed by meter id, that holds the value.
    history_attr: str | None = None


SENSORS: tuple[CitycomSensorEntityDescription, ...] = (
    CitycomSensorEntityDescription(
        key="meter_reading",
        translation_key="meter_reading",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
        value_fn=lambda r: r.last_reading,
    ),
    CitycomSensorEntityDescription(
        key="consumption_current_month",
        translation_key="consumption_current_month",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
        value_fn=lambda r: r.consumption_current_month,
    ),
    CitycomSensorEntityDescription(
        key="last_reading_date",
        translation_key="last_reading_date",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda r: _as_aware(r.last_reading_date),
    ),
    CitycomSensorEntityDescription(
        key="consumption_yesterday",
        translation_key="consumption_yesterday",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
        history_attr="yesterday",
        value_fn=lambda r: None,
    ),
    CitycomSensorEntityDescription(
        key="consumption_last_7_days",
        translation_key="consumption_last_7_days",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
        history_attr="last_7_days",
        value_fn=lambda r: None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: CitycomConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors for every meter on the account."""
    coordinator = entry.runtime_data
    async_add_entities(
        CitycomMeterSensor(coordinator, meter, description)
        for meter in coordinator.meters.values()
        for description in SENSORS
    )


class CitycomMeterSensor(CitycomMeterEntity, SensorEntity):
    """A Citycom water meter sensor."""

    entity_description: CitycomSensorEntityDescription

    def __init__(self, coordinator, meter, description) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, meter, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        if attr := self.entity_description.history_attr:
            return getattr(self.coordinator, attr).get(self.meter_id)
        reading = self.coordinator.data.get(self.meter_id)
        if reading is None:
            return None
        return self.entity_description.value_fn(reading)
