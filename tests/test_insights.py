"""Tests for night flow, budget, login expiry and alert events."""

from datetime import datetime

from citycom_mv_api.models.Alert import Alert
from homeassistant.util import dt as dt_util

from custom_components.citycom_mv_water_meter.analysis import (
    night_flow,
    project_month,
)

from .test_alerts_history import _setup


def _at(hour, minute=0, day=10):
    return datetime(2026, 10, day, hour, minute, tzinfo=dt_util.UTC)


def test_night_flow_between_two_night_readings():
    # 0.08 m3 in 4 hours is 20 litres per hour.
    assert night_flow((_at(23), 100.0), (_at(3, day=11), 100.08)) == 20.0


def test_night_flow_ignores_daytime_short_or_reset_intervals():
    assert night_flow((_at(10), 100.0), (_at(14), 100.5)) is None
    assert night_flow((_at(23), 100.0), (_at(0, 30, day=11), 100.5)) is None
    assert night_flow((_at(23), 100.0), (_at(3, day=11), 99.0)) is None
    # Across a whole day.
    assert night_flow((_at(23), 100.0), (_at(23, day=11), 101.0)) is None


def test_project_month_needs_a_full_day():
    assert project_month(1.0, datetime(2026, 10, 1, 12)) is None
    # 10 m3 in 10 days of a 31 day month.
    assert project_month(10.0, datetime(2026, 10, 11)) == 31.0


async def test_possible_leak_sensor_follows_the_night_flow(hass, mock_client, mock_imap):
    entry = await _setup(hass, {"leak_threshold": 10})
    state = hass.states.get("binary_sensor.water_meter_a_111_possible_leak")
    assert state.state == "off"

    coordinator = entry.runtime_data
    coordinator.night_flow[111] = (25.0, dt_util.utcnow())
    coordinator.async_update_listeners()
    state = hass.states.get("binary_sensor.water_meter_a_111_possible_leak")
    assert state.state == "on"
    assert state.attributes["night_flow_l_per_h"] == 25.0


async def test_no_leak_sensor_without_threshold(hass, mock_client, mock_imap):
    await _setup(hass)
    assert hass.states.get("binary_sensor.water_meter_a_111_possible_leak") is None


async def test_budget_sensors(hass, mock_client, mock_imap):
    await _setup(hass, {"monthly_budget_m3": 20, "price_regular": 10})
    # The mocked month consumption is 1.5 m3 of a 20 m3 budget.
    assert hass.states.get("sensor.water_meter_a_111_budget_used").state == "8"
    assert hass.states.get("sensor.water_meter_a_111_projected_consumption_this_month")
    assert hass.states.get("sensor.water_meter_a_111_projected_cost_this_month")


async def test_no_budget_sensors_without_budget(hass, mock_client, mock_imap):
    await _setup(hass)
    assert hass.states.get("sensor.water_meter_a_111_budget_used") is None


async def test_login_expiry_sensor(hass, mock_client, mock_imap):
    await _setup(hass)
    state = hass.states.get("sensor.citycom_account_login_expires")
    assert state is not None
    assert state.state != "unknown"


async def test_alert_events_fire_on_changes(hass, mock_client, mock_imap):
    entry = await _setup(hass)
    event = "event.water_meter_a_111_alert"
    # The alerts that already existed at startup are not reported.
    assert hass.states.get(event).state == "unknown"

    mock_client.get_active_alerts.side_effect = None
    mock_client.get_active_alerts.return_value = []
    await entry.runtime_data.async_refresh()
    state = hass.states.get(event)
    assert state.attributes["event_type"] == "alert_cleared"
    assert state.attributes["type"] == "Leak"

    mock_client.get_active_alerts.return_value = [
        Alert(meter_id=111, alert_type_id=8, date=datetime(2026, 10, 28, 1, 0))
    ]
    await entry.runtime_data.async_refresh()
    state = hass.states.get(event)
    assert state.attributes["event_type"] == "alert"
    assert state.attributes["type"] == "Other"
