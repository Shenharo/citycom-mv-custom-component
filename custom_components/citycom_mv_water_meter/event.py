"""Event platform for citycom_mv_water_meter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.event import EventEntity
from homeassistant.core import callback

from .entity import CitycomMeterEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import CitycomConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: CitycomConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up an alert event entity for every meter on the account."""
    coordinator = entry.runtime_data
    async_add_entities(
        CitycomAlertEvent(coordinator, meter) for meter in coordinator.meters.values()
    )


class CitycomAlertEvent(CitycomMeterEntity, EventEntity):
    """Fires when a Citycom alert appears or clears."""

    _attr_translation_key = "alert_event"
    _attr_event_types = ["alert", "alert_cleared"]

    def __init__(self, coordinator, meter) -> None:
        """Initialize the event entity."""
        super().__init__(coordinator, meter, "alert_event")

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fire the alert changes of the latest update."""
        for event in self.coordinator.alert_events.get(self.meter_id, []):
            data = dict(event)
            self._trigger_event(data.pop("event_type"), data)
        super()._handle_coordinator_update()
