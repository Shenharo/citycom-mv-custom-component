"""Tests for alert binary sensors, yesterday's consumption and statistics."""

from datetime import date

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.citycom_mv_water_meter.const import CONF_TOKEN, DOMAIN
from custom_components.citycom_mv_water_meter.statistics import (
    build_statistics,
    stat_base,
    statistic_id,
)

from .conftest import USER_INPUT, make_token


async def _setup(hass, options=None):
    token = make_token(hours=9)
    data = {
        **USER_INPUT,
        CONF_TOKEN: {"access_token": token.access_token, "expires": token.expires},
    }
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="user@citycom-mv.com", data=data, options=options or {}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def test_alert_and_not_reporting_binary_sensors(hass, mock_client, mock_imap):
    await _setup(hass)

    alert = hass.states.get("binary_sensor.water_meter_a_111_alert")
    assert alert.state == "on"
    assert alert.attributes["alerts"] == [{"type": "Leak", "date": "2026-10-27T08:30:00"}]
    assert hass.states.get("binary_sensor.water_meter_b_222_alert").state == "off"
    # The mocked reading is from 2026-10-27, far in the past.
    assert hass.states.get("binary_sensor.water_meter_a_111_not_reporting") is not None


async def test_yesterday_sensor(hass, mock_client, mock_imap):
    await _setup(hass)
    state = hass.states.get("sensor.water_meter_a_111_consumption_yesterday")
    assert state.state == "2.0"


async def test_alert_failure_keeps_setup(hass, mock_client, mock_imap):
    from citycom_mv_api.models.exceptions import CitycomError

    mock_client.get_active_alerts.side_effect = CitycomError(500, "boom")
    await _setup(hass)
    assert hass.states.get("binary_sensor.water_meter_a_111_alert").state == "unknown"


def test_build_statistics_is_anchored_to_current_reading():
    totals = {date(2026, 10, 25): 1.0, date(2026, 10, 26): 2.0, date(2026, 10, 27): 0.5}
    stats = build_statistics(totals, 100.0)
    assert [s["sum"] for s in stats] == [97.5, 99.5, 100.0]
    # Counted from the reading before the first day, the first day is its own use.
    base = stat_base(totals, 100.0)
    assert base == 96.5
    stats = build_statistics(totals, 100.0, base)
    assert [round(s["sum"], 4) for s in stats] == [1.0, 3.0, 3.5]
    assert statistic_id(111) == "citycom_mv_water_meter:meter_111_consumption"


async def test_statistics_base_is_saved_once(hass, mock_client, mock_imap):
    entry = await _setup(hass)

    # Mocked history 1.0 + 2.0 + 0.5 and a reading of 100.25.
    assert entry.data["stat_base"]["111"] == 96.75
    base = mock_client.import_history.call_args_list[0].args[-1]
    assert base == 96.75

    await entry.runtime_data.async_refresh()
    assert entry.data["stat_base"]["111"] == 96.75
