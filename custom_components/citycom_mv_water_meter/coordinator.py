"""DataUpdateCoordinator for citycom_mv_water_meter."""

from __future__ import annotations

from collections import deque
from datetime import timedelta
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
from .const import (
    CONF_STAT_BASE,
    CONF_TOKEN,
    DOMAIN,
    HISTORY_DAYS,
    HISTORY_UPDATE_INTERVAL,
    LOGGER,
    TOKEN_RENEW_MARGIN,
)
from .analysis import night_flow
from .statistics import daily_totals, import_history, stat_base
from .imap import ImapAuthError, ImapError, ImapSettings, async_wait_for_code

if TYPE_CHECKING:
    from datetime import datetime

    from citycom_mv_api.models.Alert import Alert
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
        update_interval: timedelta,
    ) -> None:
        """Initialize."""
        super().__init__(
            hass=hass,
            logger=LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.client = client
        self.imap = imap
        self.meters: dict[int, Meter] = {}
        self.alerts: dict[int, list[Alert]] = {}
        # Alert type titles by id, fetched once the first alert shows up.
        self.alert_types: dict[int, str] = {}
        # Total consumption of the previous full day, per meter.
        self.yesterday: dict[int, float] = {}
        # Total consumption of the 7 full days before today, per meter.
        self.last_7_days: dict[int, float] = {}
        self._history_fetched: datetime | None = None
        # The last distinct readings of a meter, as (time, m3), newest last.
        self._readings_log: dict[int, deque[tuple[datetime, float]]] = {}
        # Latest night flow per meter: (litres per hour, when it was measured).
        self.night_flow: dict[int, tuple[float, datetime]] = {}
        # Alert changes of the latest update, per meter, for the event entities.
        self.alert_events: dict[int, list[dict]] = {}
        self._alerts_seen: dict[int, set[tuple]] = {}

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
                if meter.meter_id is None:
                    continue
                # A replaced meter stays on the account, disabled, and the
                # summary API answers for it with the new meter's data.
                if meter.is_enabled is False:
                    LOGGER.debug("Skipping disabled meter %s", meter.meter_id)
                    continue
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
        self._update_night_flow(readings)
        await self._async_update_alerts()
        await self._async_update_history(readings)
        return readings

    def _update_night_flow(self, readings: dict[int, MeterReadings]) -> None:
        """Keep the distinct readings and judge the flow between night readings."""
        zone = dt_util.get_default_time_zone()
        for meter_id, reading in readings.items():
            when, value = reading.last_reading_date, reading.last_reading
            if when is None or value is None:
                continue
            when = when if when.tzinfo else when.replace(tzinfo=zone)
            log = self._readings_log.setdefault(meter_id, deque(maxlen=12))
            if log and log[-1][0] >= when:
                continue
            if log and (flow := night_flow(log[-1], (when, value))) is not None:
                self.night_flow[meter_id] = (flow, when)
            log.append((when, value))

    async def _async_update_alerts(self) -> None:
        """Fetch active alerts; failures keep the last known alerts."""
        for meter_id in self.meters:
            try:
                self.alerts[meter_id] = await self._async_call(
                    self.client.async_get_active_alerts, meter_id
                )
                LOGGER.debug(
                    "Active alerts of meter %s: %s",
                    meter_id,
                    [alert.raw for alert in self.alerts[meter_id]],
                )
            except (UpdateFailed, CitycomApiClientError) as err:
                LOGGER.debug("Alerts of meter %s unavailable: %s", meter_id, err)
        if any(self.alerts.values()) and not self.alert_types:
            await self._async_load_alert_types()
        self._update_alert_events()

    def _update_alert_events(self) -> None:
        """Describe the alerts that appeared or cleared since the last update."""
        events: dict[int, list[dict]] = {}
        for meter_id, alerts in self.alerts.items():
            current = {(a.alert_type_id, a.date or a.start_date) for a in alerts}
            if meter_id in self._alerts_seen:
                for type_id, when in current - self._alerts_seen[meter_id]:
                    events.setdefault(meter_id, []).append(
                        self._alert_event("alert", type_id, when)
                    )
                for type_id, when in self._alerts_seen[meter_id] - current:
                    events.setdefault(meter_id, []).append(
                        self._alert_event("alert_cleared", type_id, when)
                    )
            self._alerts_seen[meter_id] = current
        self.alert_events = events

    def _alert_event(self, kind: str, type_id: int | None, when) -> dict:
        return {
            "event_type": kind,
            "type": self.alert_types.get(type_id) or type_id,
            "date": when.isoformat() if when else None,
        }

    async def _async_load_alert_types(self) -> None:
        """Fetch the readable names of the alert types; ids are shown without it."""
        try:
            types = await self._async_call(self.client.async_get_alert_types)
        except (UpdateFailed, CitycomApiClientError) as err:
            LOGGER.debug("Alert types unavailable: %s", err)
            return
        self.alert_types = {
            t.alert_type_id: t.title
            for t in types
            if t.alert_type_id is not None and t.title
        }

    async def _async_update_history(self, readings: dict[int, MeterReadings]) -> None:
        """Import daily history as statistics, at most every few hours."""
        now = dt_util.utcnow()
        if self._history_fetched and now - self._history_fetched < HISTORY_UPDATE_INTERVAL:
            return
        self._history_fetched = now
        today = dt_util.now()
        for meter_id, meter in self.meters.items():
            reading = readings.get(meter_id)
            try:
                series = await self._async_call(
                    self.client.async_get_daily_history,
                    meter_id,
                    today - timedelta(days=HISTORY_DAYS),
                    today,
                )
            except (UpdateFailed, CitycomApiClientError) as err:
                LOGGER.debug("History of meter %s unavailable: %s", meter_id, err)
                continue
            if series is None or reading is None:
                continue
            name = f"Water meter {meter.number or meter_id}"
            totals = daily_totals(series)
            base = self._async_statistics_base(meter_id, totals, reading.last_reading)
            import_history(
                self.hass, meter_id, name, series, reading.last_reading, base
            )
            yesterday = (today - timedelta(days=1)).date()
            if (value := totals.get(yesterday)) is not None:
                self.yesterday[meter_id] = value
            week = [
                totals[day]
                for offset in range(1, 8)
                if (day := (today - timedelta(days=offset)).date()) in totals
            ]
            if week:
                self.last_7_days[meter_id] = round(sum(week), 3)

    def _async_statistics_base(
        self, meter_id: int, totals: dict, last_reading: float | None
    ) -> float:
        """Return the stored base of a meter's statistics, saving it on first use."""
        bases = dict(self.config_entry.data.get(CONF_STAT_BASE, {}))
        key = str(meter_id)
        if key not in bases and totals and last_reading is not None:
            bases[key] = stat_base(totals, last_reading)
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, CONF_STAT_BASE: bases},
            )
        return bases.get(key, 0.0)
