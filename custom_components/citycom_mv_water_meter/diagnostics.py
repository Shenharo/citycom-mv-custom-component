"""Diagnostics support for citycom_mv_water_meter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from .const import (
    CONF_CODE_SENDER,
    CONF_IMAP_PASSWORD,
    CONF_IMAP_USERNAME,
    CONF_TOKEN,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import CitycomConfigEntry

TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_IMAP_USERNAME,
    CONF_IMAP_PASSWORD,
    CONF_CODE_SENDER,
    CONF_TOKEN,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,  # noqa: ARG001
    entry: CitycomConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry, without credentials."""
    coordinator = entry.runtime_data
    expires = coordinator.client.token_expires_at
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "token_expires_at": expires.isoformat() if expires else None,
        "last_update_success": coordinator.last_update_success,
        "meters": {
            str(meter_id): {
                "number": meter.number,
                "model": meter.model_type_name,
                "reading": coordinator.data.get(meter_id).to_dict()
                if meter_id in coordinator.data
                else None,
                "alerts": [alert.raw for alert in coordinator.alerts.get(meter_id, [])],
                "yesterday": coordinator.yesterday.get(meter_id),
                "last_7_days": coordinator.last_7_days.get(meter_id),
            }
            for meter_id, meter in coordinator.meters.items()
        },
    }
