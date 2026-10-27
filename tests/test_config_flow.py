"""Tests for the config flow."""

from unittest.mock import patch

from citycom_mv_api.models.exceptions import CitycomError, LoginError
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.citycom_mv_water_meter.const import (
    CONF_IMAP_PASSWORD,
    CONF_TOKEN,
    DOMAIN,
)
from custom_components.citycom_mv_water_meter.imap import (
    CodeNotFoundError,
    ImapAuthError,
)

from .conftest import USER_INPUT, make_token


async def _start(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def _submit_and_wait(hass, flow_id, user_input):
    """Submit the user step and let the background login finish."""
    result = await hass.config_entries.flow.async_configure(flow_id, user_input)
    if result["type"] is FlowResultType.SHOW_PROGRESS:
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(flow_id)
    return result


async def test_email_code_login_creates_entry(hass, mock_client, mock_imap):
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM

    result = await _submit_and_wait(hass, result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "user@citycom-mv.com"
    assert result["data"][CONF_PASSWORD] == "secret"
    assert result["data"][CONF_TOKEN]["access_token"] == "access"
    mock_client.login.assert_awaited_once_with(channel="email")
    mock_client.verify_2fa_code.assert_awaited_once_with("309968")


async def test_manual_code_when_email_missing(hass, mock_client, mock_imap):
    result = await _start(hass)
    with patch(
        "custom_components.citycom_mv_water_meter.coordinator.async_wait_for_code",
        side_effect=CodeNotFoundError("no email"),
    ):
        result = await _submit_and_wait(hass, result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "code"

    mock_client.verify_2fa_code.side_effect = CitycomError(400, "Invalid code")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "000000"}
    )
    assert result["errors"] == {"base": "invalid_code"}

    mock_client.verify_2fa_code.side_effect = None
    mock_client.verify_2fa_code.return_value = None
    mock_client._token = make_token()  # noqa: SLF001
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": " 123456 "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    mock_client.verify_2fa_code.assert_awaited_with("123456")


async def test_mailbox_rejected(hass, mock_client, mock_imap):
    mock_imap.check_login.side_effect = ImapAuthError("bad app password")
    result = await _start(hass)
    result = await _submit_and_wait(hass, result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "imap_auth"}
    mock_client.login.assert_not_awaited()


async def test_citycom_password_rejected(hass, mock_client, mock_imap):
    mock_client.login.side_effect = CitycomError(400, "Invalid username or password")
    result = await _start(hass)
    result = await _submit_and_wait(hass, result["flow_id"], USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "auth"}


async def test_citycom_wrapped_login_error_is_auth(hass, mock_client, mock_imap):
    mock_client.login.side_effect = LoginError(401, "invalid_grant")
    result = await _start(hass)
    result = await _submit_and_wait(hass, result["flow_id"], USER_INPUT)
    assert result["errors"] == {"base": "auth"}


async def test_duplicate_account_aborts(hass, mock_client, mock_imap):
    MockConfigEntry(
        domain=DOMAIN, unique_id="user@citycom-mv.com", data=USER_INPUT
    ).add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_updates_passwords(hass, mock_client, mock_imap):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="user@citycom-mv.com", data=USER_INPUT
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "user"

    new_input = {**USER_INPUT, CONF_PASSWORD: "new", CONF_IMAP_PASSWORD: "new-app"}
    with patch(
        "custom_components.citycom_mv_water_meter.async_setup_entry",
        return_value=True,
    ):
        result = await _submit_and_wait(hass, result["flow_id"], new_input)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new"
    assert entry.data[CONF_IMAP_PASSWORD] == "new-app"
    assert entry.data[CONF_TOKEN]["access_token"] == "access"
