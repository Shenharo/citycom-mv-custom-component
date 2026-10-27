"""Fixtures for Citycom MV tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from citycom_mv_api.models.Alert import Alert
from citycom_mv_api.models.AlertType import AlertType
from citycom_mv_api.models.ConsumptionTimeSeries import ConsumptionTimeSeries
from citycom_mv_api.models.CustomerInformation import CustomerInformation
from citycom_mv_api.models.jwt import JWT
from citycom_mv_api.models.login_challenge import LoginChallenge
from citycom_mv_api.models.Reading import MeterReadings
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from custom_components.citycom_mv_water_meter.const import (
    CONF_CODE_SENDER,
    CONF_IMAP_FOLDER,
    CONF_IMAP_HOST,
    CONF_IMAP_PASSWORD,
    CONF_IMAP_PORT,
    CONF_IMAP_USERNAME,
)

pytest_plugins = ["pytest_homeassistant_custom_component"]

USER_INPUT = {
    CONF_USERNAME: "User@citycom-mv.com",
    CONF_PASSWORD: "secret",
    CONF_IMAP_USERNAME: "me@gmail.com",
    CONF_IMAP_PASSWORD: "app-password",
    CONF_IMAP_HOST: "imap.gmail.com",
    CONF_IMAP_PORT: 993,
    CONF_IMAP_FOLDER: "INBOX",
    CONF_CODE_SENDER: "citycom@gaon.com",
}

CUSTOMER = CustomerInformation.from_dict(
    {
        "userName": "user@citycom-mv.com",
        "properties": [
            {
                "propertyId": 1,
                "meters": [
                    {"meterId": 111, "number": "A-111", "modelTypeName": "Arad"},
                    {"meterId": 222, "number": "B-222"},
                    # Replaced meter: still listed, disabled.
                    {"meterId": 333, "number": "OLD-333", "isEnabled": False},
                ],
            }
        ],
    }
)


def make_token(hours: float = 10) -> JWT:
    expires = datetime.now(UTC) + timedelta(hours=hours)
    return JWT(access_token="access", expires=expires.isoformat())


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    return


@pytest.fixture
def mock_imap():
    """Patch the mailbox: login works and the code email is there."""
    with (
        patch(
            "custom_components.citycom_mv_water_meter.config_flow.check_login"
        ) as check,
        patch(
            "custom_components.citycom_mv_water_meter.imap.find_code",
            return_value="482915",
        ) as find,
    ):
        yield MagicMock(check_login=check, find_code=find)


@pytest.fixture
def mock_client():
    """Patch the library client used by the integration."""
    client = MagicMock()
    client._token = None  # noqa: SLF001
    client.logged_in = False

    def get_token():
        return client._token  # noqa: SLF001

    def expires_at():
        token = client._token  # noqa: SLF001
        return datetime.fromisoformat(token.expires) if token else None

    async def login(channel="sms"):
        return LoginChallenge(
            pending_token="pending", channel=channel, masked_contact="m***@gmail.com"
        )

    async def verify(code):
        client._token = make_token()  # noqa: SLF001
        return client._token  # noqa: SLF001

    async def load_jwt_token(token):
        client._token = token  # noqa: SLF001

    async def reading(meter_id):
        return MeterReadings(
            meter_id=int(meter_id),
            consumption_current_month=1.5,
            last_reading=100.25 if meter_id == "111" else 7.0,
            last_reading_date=datetime(2026, 10, 27, 6, 0),
        )

    client.get_token = MagicMock(side_effect=get_token)
    type(client).token_expires_at = property(lambda self: expires_at())
    client.login = AsyncMock(side_effect=login)
    client.verify_2fa_code = AsyncMock(side_effect=verify)
    client.load_jwt_token = AsyncMock(side_effect=load_jwt_token)
    client.get_customer = AsyncMock(return_value=CUSTOMER)
    client.get_last_meter_reading = AsyncMock(side_effect=reading)

    async def alerts(meter_id):
        if meter_id == "111":
            return [Alert(meter_id=111, alert_type_id=7, date=datetime(2026, 10, 27, 8, 30))]
        return []

    async def history(meter_id, period, from_date, to_date):
        series = ConsumptionTimeSeries()
        today = datetime.now().date()
        series.add(today - timedelta(days=2), 1.0)
        series.add(today - timedelta(days=1), 2.0)
        series.add(today, 0.5)
        return series

    async def alert_types():
        return [AlertType(alert_type_id=7, title="Leak"), AlertType(alert_type_id=8, title="Other")]

    client.get_active_alerts = AsyncMock(side_effect=alerts)
    client.get_alert_types = AsyncMock(side_effect=alert_types)
    client.get_historical_data = AsyncMock(side_effect=history)
    with (
        patch(
            "custom_components.citycom_mv_water_meter.api.CityComMVClient",
            return_value=client,
        ),
        patch(
            "custom_components.citycom_mv_water_meter.coordinator.import_history"
        ) as import_history,
    ):
        client.import_history = import_history
        yield client
