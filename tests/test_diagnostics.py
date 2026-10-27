"""Tests for diagnostics and the 7-day sensor."""

from custom_components.citycom_mv_water_meter.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .test_alerts_history import _setup


async def test_diagnostics_redacts_credentials(hass, mock_client, mock_imap):
    entry = await _setup(hass)

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["entry"]["password"] == "**REDACTED**"
    assert result["entry"]["imap_password"] == "**REDACTED**"
    assert result["entry"]["token"] == "**REDACTED**"
    assert "secret" not in str(result)
    assert "app-password" not in str(result)
    assert result["meters"]["111"]["number"] == "A-111"
    assert result["meters"]["111"]["alerts"] == [{}]
    assert result["meters"]["111"]["yesterday"] == 2.0


async def test_last_7_days_sensor(hass, mock_client, mock_imap):
    await _setup(hass)
    state = hass.states.get("sensor.water_meter_a_111_consumption_last_7_days")
    # Mock history: 1.0 two days ago + 2.0 yesterday (today's 0.5 is excluded).
    assert state.state == "3.0"
