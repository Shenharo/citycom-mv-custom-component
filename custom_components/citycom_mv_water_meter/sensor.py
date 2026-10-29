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
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfVolume
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTRIBUTION,
    CONF_ALLOWANCE,
    CONF_BUDGET,
    CONF_PERSONS,
    CONF_PRICE_DRAIN,
    CONF_PRICE_FIXED,
    CONF_PRICE_OVER,
    CONF_PRICE_REGULAR,
    DOMAIN,
    MANUFACTURER,
)
from .analysis import project_month
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
    # A value worked out from the options ("cost", "budget_used", "projected" or
    # "projected_cost"); created only when the option it needs is set.
    calc: str | None = None
    requires_option: str | None = None


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
        calc="cost",
        requires_option=CONF_PRICE_REGULAR,
        value_fn=lambda r: None,
    ),
    CitycomSensorEntityDescription(
        key="projected_consumption",
        translation_key="projected_consumption",
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=1,
        calc="projected",
        requires_option=CONF_BUDGET,
        value_fn=lambda r: None,
    ),
    CitycomSensorEntityDescription(
        key="budget_used",
        translation_key="budget_used",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        calc="budget_used",
        requires_option=CONF_BUDGET,
        value_fn=lambda r: None,
    ),
    CitycomSensorEntityDescription(
        key="projected_cost",
        translation_key="projected_cost",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        calc="projected_cost",
        requires_option=CONF_PRICE_REGULAR,
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
        if not description.requires_option
        or entry.options.get(description.requires_option)
    )
    async_add_entities([CitycomLoginSensor(coordinator, entry.entry_id)])


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
        if self.entity_description.calc in ("cost", "projected_cost"):
            return self.hass.config.currency
        return self.entity_description.native_unit_of_measurement

    @property
    def last_reset(self) -> datetime | None:
        """The cost starts again each month."""
        if self.entity_description.calc == "cost":
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
        if calc := self.entity_description.calc:
            return self._calc(calc, reading.consumption_current_month)
        return self.entity_description.value_fn(reading)

    def _calc(self, calc: str, consumption: float | None) -> float | None:
        """Work out a value that depends on the options."""
        if consumption is None:
            return None
        options = self.coordinator.config_entry.options
        if calc == "cost":
            return self._cost(consumption)
        if calc == "budget_used":
            return round(consumption / options[CONF_BUDGET] * 100)
        projected = project_month(consumption, dt_util.now())
        if projected is None:
            return None
        if calc == "projected":
            return projected
        return self._cost(projected)


class CitycomLoginSensor(CoordinatorEntity, SensorEntity):
    """When the current Citycom login expires (diagnostic, one per account)."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "login_expires"

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_login_expires"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Citycom account",
            manufacturer=MANUFACTURER,
        )

    @property
    def native_value(self) -> datetime | None:
        """Return when the token expires."""
        return self.coordinator.client.token_expires_at
