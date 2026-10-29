"""Config flow for citycom_mv_water_meter."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import selector
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    CitycomApiClient,
    CitycomApiClientAuthenticationError,
    CitycomApiClientCodeError,
    CitycomApiClientCommunicationError,
    CitycomApiClientError,
)
from .const import (
    CONF_ALLOWANCE,
    CONF_BUDGET,
    CONF_LEAK_THRESHOLD,
    CONF_PERSONS,
    CONF_PRICE_DRAIN,
    CONF_PRICE_FIXED,
    CONF_PRICE_OVER,
    CONF_PRICE_REGULAR,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
    CONF_CODE_SENDER,
    CONF_IMAP_FOLDER,
    CONF_IMAP_HOST,
    CONF_IMAP_PASSWORD,
    CONF_IMAP_PORT,
    CONF_IMAP_USERNAME,
    CONF_TOKEN,
    DEFAULT_CODE_SENDER,
    DEFAULT_IMAP_FOLDER,
    DEFAULT_IMAP_HOST,
    DEFAULT_IMAP_PORT,
    DOMAIN,
    LOGGER,
)
from .coordinator import async_login_with_email_code
from .imap import (
    CodeNotFoundError,
    ImapAuthError,
    ImapError,
    ImapSettings,
    check_login,
)

TEXT = selector.TextSelector()


def _number(step: float | str = "any") -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0, step=step, mode=selector.NumberSelectorMode.BOX
        )
    )
PASSWORD = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)
EMAIL = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)
)
PORT = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=1, max=65535, mode=selector.NumberSelectorMode.BOX
    )
)


def imap_settings(data: Mapping[str, Any]) -> ImapSettings:
    """Build IMAP settings from config entry data."""
    return ImapSettings(
        host=data[CONF_IMAP_HOST],
        port=int(data[CONF_IMAP_PORT]),
        username=data[CONF_IMAP_USERNAME],
        password=data[CONF_IMAP_PASSWORD],
        folder=data[CONF_IMAP_FOLDER],
        sender=data[CONF_CODE_SENDER],
    )


def _user_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    def d(key: str, default: Any = vol.UNDEFINED) -> dict[str, Any]:
        return {"default": defaults.get(key, default)}

    return vol.Schema(
        {
            vol.Required(CONF_USERNAME, **d(CONF_USERNAME)): TEXT,
            vol.Required(CONF_PASSWORD): PASSWORD,
            vol.Required(CONF_IMAP_USERNAME, **d(CONF_IMAP_USERNAME)): EMAIL,
            vol.Required(CONF_IMAP_PASSWORD): PASSWORD,
            vol.Required(CONF_IMAP_HOST, **d(CONF_IMAP_HOST, DEFAULT_IMAP_HOST)): TEXT,
            vol.Required(CONF_IMAP_PORT, **d(CONF_IMAP_PORT, DEFAULT_IMAP_PORT)): PORT,
            vol.Required(
                CONF_IMAP_FOLDER, **d(CONF_IMAP_FOLDER, DEFAULT_IMAP_FOLDER)
            ): TEXT,
            vol.Required(
                CONF_CODE_SENDER, **d(CONF_CODE_SENDER, DEFAULT_CODE_SENDER)
            ): TEXT,
        }
    )


class CitycomFlowHandler(ConfigFlow, domain=DOMAIN):
    """Config flow for Citycom MV.

    Citycom requires a 2FA code on every login. The code is requested by
    email and read from the mailbox over IMAP, so later logins (every 10
    hours) need no user action. If the email does not arrive, the user can
    type the code instead.
    """

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> CitycomOptionsFlow:  # noqa: ARG004
        """Return the options flow."""
        return CitycomOptionsFlow()

    def __init__(self) -> None:
        """Initialize."""
        self._data: dict[str, Any] = {}
        self._client: CitycomApiClient | None = None
        self._login_task: asyncio.Task | None = None
        self._progress_shown = False
        self._errors: dict[str, str] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the Citycom account and the mailbox the codes are sent to."""
        errors, self._errors = self._errors, {}
        if user_input is not None:
            if self.source != SOURCE_REAUTH:
                await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
                self._abort_if_unique_id_configured()
            self._data = {**self._data, **user_input}
            errors = await self._async_check_mailbox()
            if not errors:
                return await self.async_step_login()

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input or self._data),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Ask for the passwords again when a login is rejected."""
        self._data = {k: v for k, v in entry_data.items() if k != CONF_TOKEN}
        return await self.async_step_user()

    async def async_step_login(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Log in and wait for the code email."""
        if self._login_task is None:
            self._client = CitycomApiClient(
                username=self._data[CONF_USERNAME],
                password=self._data[CONF_PASSWORD],
                session=async_get_clientsession(self.hass),
            )
            self._login_task = self.hass.async_create_task(
                async_login_with_email_code(
                    self.hass, self._client, imap_settings(self._data)
                )
            )
        if not self._login_task.done():
            self._progress_shown = True
            return self.async_show_progress(
                step_id="login",
                progress_action="wait_for_email",
                progress_task=self._login_task,
            )

        task, self._login_task = self._login_task, None
        next_step = self._login_result(task)
        if self._progress_shown:
            self._progress_shown = False
            return self.async_show_progress_done(next_step_id=next_step)
        # The task is started eagerly and can finish (e.g. on a rejected
        # password) before any progress was shown. progress_done would then
        # hand the submitted form to the next step, so call it directly.
        return await getattr(self, f"async_step_{next_step}")()

    def _login_result(self, task: asyncio.Task) -> str:
        """Return the step to go to after the login task."""
        try:
            task.result()
        except CodeNotFoundError as err:
            LOGGER.warning(err)
            return "code"
        except CitycomApiClientAuthenticationError as err:
            LOGGER.warning(err)
            self._errors = {"base": "auth"}
        except CitycomApiClientCodeError as err:
            LOGGER.warning(err)
            self._errors = {"base": "invalid_code"}
        except CitycomApiClientCommunicationError as err:
            LOGGER.error(err)
            self._errors = {"base": "connection"}
        except ImapAuthError as err:
            LOGGER.warning(err)
            self._errors = {"base": "imap_auth"}
        except ImapError as err:
            LOGGER.error(err)
            self._errors = {"base": "imap_connection"}
        except CitycomApiClientError as err:
            LOGGER.exception(err)
            self._errors = {"base": "unknown"}
        else:
            return "finish"
        return "user"

    async def async_step_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user type the code when the email could not be read."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self._client.async_verify_code(user_input["code"].strip())
            except CitycomApiClientCodeError:
                errors["base"] = "invalid_code"
            except CitycomApiClientError as err:
                LOGGER.error(err)
                errors["base"] = "connection"
            else:
                return await self.async_step_finish()

        return self.async_show_form(
            step_id="code",
            data_schema=vol.Schema({vol.Required("code"): TEXT}),
            description_placeholders={
                "sender": self._data[CONF_CODE_SENDER],
                "mailbox": self._data[CONF_IMAP_USERNAME],
            },
            errors=errors,
        )

    async def async_step_finish(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Save the entry with the new token."""
        data = {**self._data, CONF_TOKEN: self._client.token}
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data=data
            )
        return self.async_create_entry(title=data[CONF_USERNAME], data=data)

    async def _async_check_mailbox(self) -> dict[str, str]:
        """Return form errors if the mailbox cannot be opened."""
        try:
            await self.hass.async_add_executor_job(
                check_login, imap_settings(self._data)
            )
        except ImapAuthError as err:
            LOGGER.warning(err)
            return {"base": "imap_auth"}
        except ImapError as err:
            LOGGER.error(err)
            return {"base": "imap_connection"}
        return {}


class CitycomOptionsFlow(OptionsFlowWithReload):
    """Change the polling interval and the mail folder."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options form."""
        if user_input is not None:
            user_input[CONF_UPDATE_INTERVAL] = int(user_input[CONF_UPDATE_INTERVAL])
            if CONF_PERSONS in user_input:
                user_input[CONF_PERSONS] = int(user_input[CONF_PERSONS])
            return self.async_create_entry(data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=current.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=MIN_UPDATE_INTERVAL,
                            max=MAX_UPDATE_INTERVAL,
                            step=1,
                            unit_of_measurement="min",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_IMAP_FOLDER,
                        default=current.get(CONF_IMAP_FOLDER, DEFAULT_IMAP_FOLDER),
                    ): TEXT,
                    vol.Optional(
                        CONF_PRICE_REGULAR,
                        description={"suggested_value": current.get(CONF_PRICE_REGULAR)},
                    ): _number(),
                    vol.Optional(
                        CONF_PRICE_OVER,
                        description={"suggested_value": current.get(CONF_PRICE_OVER)},
                    ): _number(),
                    vol.Optional(
                        CONF_PRICE_DRAIN,
                        description={"suggested_value": current.get(CONF_PRICE_DRAIN)},
                    ): _number(),
                    vol.Optional(
                        CONF_PRICE_FIXED,
                        description={"suggested_value": current.get(CONF_PRICE_FIXED)},
                    ): _number(),
                    vol.Optional(
                        CONF_ALLOWANCE,
                        description={"suggested_value": current.get(CONF_ALLOWANCE)},
                    ): _number(),
                    vol.Optional(
                        CONF_PERSONS,
                        description={"suggested_value": current.get(CONF_PERSONS)},
                    ): _number(step=1),
                    vol.Optional(
                        CONF_BUDGET,
                        description={"suggested_value": current.get(CONF_BUDGET)},
                    ): _number(),
                    vol.Optional(
                        CONF_LEAK_THRESHOLD,
                        description={"suggested_value": current.get(CONF_LEAK_THRESHOLD)},
                    ): _number(),
                }
            ),
        )
