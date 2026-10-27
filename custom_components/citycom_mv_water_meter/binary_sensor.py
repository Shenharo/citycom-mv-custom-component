"""Binary sensor platform for citycom_mv_water_meter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.util import dt as dt_util

from .const import STALE_READING_AFTER
from .entity import CitycomMeterEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import CitycomConfigEntry
    from .coordinator import CitycomDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class CitycomBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a Citycom meter binary sensor."""

    is_on_fn: Callable[[CitycomDataUpdateCoordinator, int], bool | None]
    attrs_fn: Callable[[CitycomDataUpdateCoordinator, int], dict[str, Any]] | None = None


def _alerts_on(coordinator: CitycomDataUpdateCoordinator, meter_id: int) -> bool | None:
    alerts = coordinator.alerts.get(meter_id)
    return None if alerts is None else bool(alerts)


def _alert_attrs(
    coordinator: CitycomDataUpdateCoordinator, meter_id: int
) -> dict[str, Any]:
    return {
        "alerts": [
            alert.alert_type or alert.description or alert.alert_type_id
            for alert in coordinator.alerts.get(meter_id, [])
        ]
    }


def _not_reporting(
    coordinator: CitycomDataUpdateCoordinator, meter_id: int
) -> bool | None:
    reading = coordinator.data.get(meter_id)
    last = reading.last_reading_date if reading else None
    if last is None:
        return None
    if last.tzinfo is None:
        last = last.replace(tzinfo=dt_util.get_default_time_zone())
    return dt_util.utcnow() - last > STALE_READING_AFTER


BINARY_SENSORS: tuple[CitycomBinarySensorDescription, ...] = (
    CitycomBinarySensorDescription(
        key="alert",
        translation_key="alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=_alerts_on,
        attrs_fn=_alert_attrs,
    ),
    CitycomBinarySensorDescription(
        key="not_reporting",
        translation_key="not_reporting",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=_not_reporting,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: CitycomConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensors for every meter on the account."""
    coordinator = entry.runtime_data
    async_add_entities(
        CitycomMeterBinarySensor(coordinator, meter, description)
        for meter in coordinator.meters.values()
        for description in BINARY_SENSORS
    )


class CitycomMeterBinarySensor(CitycomMeterEntity, BinarySensorEntity):
    """A Citycom water meter binary sensor."""

    entity_description: CitycomBinarySensorDescription

    def __init__(self, coordinator, meter, description) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, meter, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return True when the problem is present."""
        return self.entity_description.is_on_fn(self.coordinator, self.meter_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        fn = self.entity_description.attrs_fn
        return fn(self.coordinator, self.meter_id) if fn else None
