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

from .const import (
    CONF_ALLOWANCE,
    CONF_PERSONS,
    CONF_PRICE_DRAIN,
    CONF_PRICE_FIXED,
    CONF_PRICE_OVER,
    CONF_PRICE_REGULAR,
)
from .entity import CitycomMeterEntity
from .pricing import compute_cost

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
    # A cost estimate from the price options; only created when a price is set.
    is_cost: bool = False


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
    CitycomSensorEntityDescription(
        key="cost_this_month",
        translation_key="cost_this_month",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        is_cost=True,
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
    has_price = bool(entry.options.get(CONF_PRICE_REGULAR))
    async_add_entities(
        CitycomMeterSensor(coordinator, meter, description)
        for meter in coordinator.meters.values()
        for description in SENSORS
        if has_price or not description.is_cost
    )


class CitycomMeterSensor(CitycomMeterEntity, SensorEntity):
    """A Citycom water meter sensor."""

    entity_description: CitycomSensorEntityDescription

    def __init__(self, coordinator, meter, description) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, meter, description.key)
        self.entity_description = description
        self._meter = meter

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit; the cost uses the Home Assistant currency."""
        if self.entity_description.is_cost:
            return self.hass.config.currency
        return self.entity_description.native_unit_of_measurement

    @property
    def last_reset(self) -> datetime | None:
        """The cost starts again each month."""
        if self.entity_description.is_cost:
            return dt_util.start_of_local_day(dt_util.now().replace(day=1))
        return None

    def _cost(self, consumption: float) -> float:
        """Estimate the cost of the month's consumption from the price options."""
        options = self.coordinator.config_entry.options
        persons = options.get(CONF_PERSONS) or (
            self._meter.property.number_of_persons if self._meter.property else 0
        )
        return round(
            compute_cost(
                consumption,
                regular=options[CONF_PRICE_REGULAR],
                over=options.get(CONF_PRICE_OVER),
                drain=options.get(CONF_PRICE_DRAIN, 0.0),
                fixed=options.get(CONF_PRICE_FIXED, 0.0),
                allowance_per_person=options.get(CONF_ALLOWANCE, 0.0),
                persons=int(persons),
            ),
            2,
        )

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        if attr := self.entity_description.history_attr:
            return getattr(self.coordinator, attr).get(self.meter_id)
        reading = self.coordinator.data.get(self.meter_id)
        if reading is None:
            return None
        if self.entity_description.is_cost:
            if reading.consumption_current_month is None:
                return None
            return self._cost(reading.consumption_current_month)
        return self.entity_description.value_fn(reading)
