"""Custom integration to integrate Citycom MV water meters with Home Assistant.

For more details about this integration, please refer to
https://github.com/Shenharo/citycom-mv-custom-component
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CitycomApiClient
from .config_flow import imap_settings
from .const import CONF_TOKEN, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN
from .coordinator import CitycomDataUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

type CitycomConfigEntry = ConfigEntry[CitycomDataUpdateCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: CitycomConfigEntry) -> bool:
    """Set up this integration using UI."""
    client = CitycomApiClient(
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        session=async_get_clientsession(hass),
    )
    if token := entry.data.get(CONF_TOKEN):
        await client.async_set_token(token)

    coordinator = CitycomDataUpdateCoordinator(
        hass=hass,
        entry=entry,
        client=client,
        # Options (set with the Configure button) override the setup values.
        imap=imap_settings({**entry.data, **entry.options}),
        update_interval=timedelta(
            minutes=entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        ),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    _async_remove_stale_devices(hass, entry, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _async_remove_stale_devices(
    hass: HomeAssistant,
    entry: CitycomConfigEntry,
    coordinator: CitycomDataUpdateCoordinator,
) -> None:
    """Remove devices of meters that were replaced or removed from the account."""
    current = {(DOMAIN, str(meter_id)) for meter_id in coordinator.meters}
    device_registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if not device.identifiers & current:
            device_registry.async_remove_device(device.id)


async def async_unload_entry(hass: HomeAssistant, entry: CitycomConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
