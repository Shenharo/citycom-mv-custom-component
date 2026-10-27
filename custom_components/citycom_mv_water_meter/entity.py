"""Base entity for citycom_mv_water_meter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER
from .coordinator import CitycomDataUpdateCoordinator

if TYPE_CHECKING:
    from citycom_mv_api.models.Meter import Meter


class CitycomMeterEntity(CoordinatorEntity[CitycomDataUpdateCoordinator]):
    """An entity belonging to one water meter device."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: CitycomDataUpdateCoordinator, meter: Meter, key: str
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.meter_id = meter.meter_id
        self._attr_unique_id = f"{meter.meter_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(meter.meter_id))},
            name=f"Water meter {meter.number or meter.meter_id}",
            manufacturer=MANUFACTURER,
            model=meter.model_type_name,
            serial_number=meter.number,
        )

    @property
    def available(self) -> bool:
        """Return True if the meter has a reading."""
        return super().available and self.meter_id in self.coordinator.data
