"""DataUpdateCoordinator for citycom_mv_water_meter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    CitycomApiClient,
    CitycomApiClientAuthenticationError,
    CitycomApiClientCodeError,
    CitycomApiClientError,
    CitycomApiClientTokenExpiredError,
)
from .const import CONF_TOKEN, DOMAIN, LOGGER, TOKEN_RENEW_MARGIN, UPDATE_INTERVAL
from .imap import ImapAuthError, ImapError, ImapSettings, async_wait_for_code

if TYPE_CHECKING:
    from citycom_mv_api.models.Meter import Meter
    from citycom_mv_api.models.Reading import MeterReadings
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


async def async_login_with_email_code(
    hass: HomeAssistant, client: CitycomApiClient, imap: ImapSettings
) -> None:
    """Log in, reading the 2FA code from the mailbox."""
    started = dt_util.utcnow()
    challenge = await client.async_start_login("email")
    if challenge is None:
        return
    LOGGER.debug("2FA code sent to %s, waiting for it", challenge.masked_contact)
    code = await async_wait_for_code(hass, imap, since=started)
    await client.async_verify_code(code)


class CitycomDataUpdateCoordinator(DataUpdateCoordinator[dict[int, "MeterReadings"]]):
    """Fetches the last reading of every meter on the account."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: CitycomApiClient,
        imap: ImapSettings,
    ) -> None:
        """Initialize."""
        super().__init__(
            hass=hass,
            logger=LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.imap = imap
        self.meters: dict[int, Meter] = {}

    async def _async_ensure_token(self, *, force: bool = False) -> None:
        """Log in again when the token is missing or about to expire."""
        expires = self.client.token_expires_at
        if not force and expires and expires - dt_util.utcnow() > TOKEN_RENEW_MARGIN:
            return
        LOGGER.debug("Token expires at %s, logging in again", expires)
        try:
            await async_login_with_email_code(self.hass, self.client, self.imap)
        except CitycomApiClientAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                f"Citycom rejected the password: {err}"
            ) from err
        except ImapAuthError as err:
            raise ConfigEntryAuthFailed(
                f"The mailbox rejected the login: {err}"
            ) from err
        except (ImapError, CitycomApiClientCodeError, CitycomApiClientError) as err:
            raise UpdateFailed(f"Login with emailed code failed: {err}") from err

        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={**self.config_entry.data, CONF_TOKEN: self.client.token},
        )

    async def _async_call(self, func, *args):
        """Call the API, logging in again once if the token is rejected."""
        await self._async_ensure_token()
        try:
            return await func(*args)
        except CitycomApiClientTokenExpiredError:
            await self._async_ensure_token(force=True)
        try:
            return await func(*args)
        except CitycomApiClientTokenExpiredError as err:
            raise UpdateFailed(f"Token rejected right after login: {err}") from err
        except CitycomApiClientError as err:
            raise UpdateFailed(err) from err

    async def _async_setup(self) -> None:
        """Discover meters before the first refresh."""
        try:
            customer = await self._async_call(self.client.async_get_customer)
        except CitycomApiClientError as err:
            raise UpdateFailed(err) from err

        for property_ in customer.properties or []:
            for meter in property_.meters or []:
                if meter.meter_id is not None:
                    self.meters[meter.meter_id] = meter
        LOGGER.debug("Discovered meters: %s", list(self.meters))

    async def _async_update_data(self) -> dict[int, MeterReadings]:
        """Fetch the last reading of every meter."""
        readings: dict[int, MeterReadings] = {}
        try:
            for meter_id in self.meters:
                reading = await self._async_call(
                    self.client.async_get_last_reading, meter_id
                )
                if reading is not None:
                    readings[meter_id] = reading
        except CitycomApiClientError as err:
            raise UpdateFailed(err) from err
        return readings
