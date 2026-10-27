"""Tests for setting up the integration, its sensors and automatic re-login."""

from datetime import timedelta

from citycom_mv_api.models.exceptions import CitycomError
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.citycom_mv_water_meter.const import CONF_TOKEN, DOMAIN

from .conftest import USER_INPUT, make_token


def _entry(hass, token=None):
    data = dict(USER_INPUT)
    if token:
        data[CONF_TOKEN] = {
            "access_token": token.access_token,
            "expires": token.expires,
        }
    entry = MockConfigEntry(domain=DOMAIN, unique_id="user@citycom-mv.com", data=data)
    entry.add_to_hass(hass)
    return entry


async def test_setup_with_stored_token_creates_sensors(hass, mock_client, mock_imap):
    entry = _entry(hass, make_token(hours=9))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    # A valid stored token is reused: no new login, no email.
    mock_client.login.assert_not_awaited()

    reading = hass.states.get("sensor.water_meter_a_111_meter_reading")
    assert reading.state == "100.25"
    assert reading.attributes["unit_of_measurement"] == "m³"
    assert reading.attributes["device_class"] == "water"
    assert reading.attributes["state_class"] == "total_increasing"
    assert hass.states.get("sensor.water_meter_b_222_meter_reading").state == "7.0"
    month = hass.states.get("sensor.water_meter_a_111_consumption_this_month")
    assert month.state == "1.5"
    assert hass.states.get("sensor.water_meter_a_111_last_reading_time") is not None

    # The disabled (replaced) meter gets no sensors and is not polled.
    assert hass.states.get("sensor.water_meter_old_333_meter_reading") is None
    polled = {c.args[0] for c in mock_client.get_last_meter_reading.await_args_list}
    assert polled == {"111", "222"}

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_expiring_token_logs_in_with_email_code(
    hass, mock_client, mock_imap, freezer: FrozenDateTimeFactory
):
    entry = _entry(hass, make_token(hours=1))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    mock_client.login.assert_not_awaited()

    # 30 minutes later less than the renew margin is left: log in again.
    freezer.tick(timedelta(minutes=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    mock_client.login.assert_awaited_once_with(channel="email")
    mock_client.verify_2fa_code.assert_awaited_once_with("482915")
    stored = entry.data[CONF_TOKEN]
    assert stored["expires"] == mock_client._token.expires  # noqa: SLF001
    assert entry.state is ConfigEntryState.LOADED


async def test_rejected_token_logs_in_again(hass, mock_client, mock_imap):
    entry = _entry(hass, make_token(hours=9))
    mock_client.get_customer.side_effect = [
        CitycomError(401, "Unauthorized"),
        mock_client.get_customer.return_value,
    ]
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    mock_client.login.assert_awaited_once()


async def test_rejected_password_starts_reauth(hass, mock_client, mock_imap):
    mock_client.login.side_effect = CitycomError(400, "Invalid username or password")
    entry = _entry(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_connection_failure_retries(hass, mock_client, mock_imap):
    mock_client.get_last_meter_reading.side_effect = CitycomError(-1, "time out")
    entry = _entry(hass, make_token(hours=9))
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_stale_meter_device_is_removed(hass, mock_client, mock_imap):
    entry = _entry(hass, make_token(hours=9))
    device_registry = dr.async_get(hass)
    old = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "333")}
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert device_registry.async_get(old.id) is None
    identifiers = {
        identifier
        for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id)
        for identifier in device.identifiers
    }
    assert identifiers == {(DOMAIN, "111"), (DOMAIN, "222")}
