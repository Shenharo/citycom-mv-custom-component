"""Thin wrapper around citycom-mv-api that maps its errors to integration errors."""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import TYPE_CHECKING, Any

from citycom_mv_api.citycom_mv_client import CityComMVClient
from citycom_mv_api.models.exceptions import CitycomError, LoginError, TokenExpiredError
from citycom_mv_api.models.jwt import JWT

if TYPE_CHECKING:
    import aiohttp
    from citycom_mv_api.models.CustomerInformation import CustomerInformation
    from citycom_mv_api.models.login_challenge import LoginChallenge
    from citycom_mv_api.models.Reading import MeterReadings


class CitycomApiClientError(Exception):
    """General API error."""


class CitycomApiClientCommunicationError(CitycomApiClientError):
    """Communication error."""


class CitycomApiClientAuthenticationError(CitycomApiClientError):
    """The username or password was rejected."""


class CitycomApiClientCodeError(CitycomApiClientError):
    """The 2FA code was rejected."""


class CitycomApiClientTokenExpiredError(CitycomApiClientError):
    """The token expired or was rejected; log in again."""


def _map_error(err: Exception) -> CitycomApiClientError:
    """Translate a citycom-mv-api exception into an integration exception."""
    if isinstance(err, TokenExpiredError):
        return CitycomApiClientTokenExpiredError(str(err))
    # Wrapped errors keep the real cause, which tells whether the server
    # rejected the request or was just unreachable.
    cause = err
    while isinstance(cause, LoginError) and cause.code == -1 and cause.__cause__:
        cause = cause.__cause__
    if isinstance(cause, LoginError) or (
        isinstance(cause, CitycomError) and cause.code in (400, 401, 403)
    ):
        return CitycomApiClientAuthenticationError(str(cause))
    if isinstance(cause, CitycomError):
        return CitycomApiClientCommunicationError(str(cause))
    return CitycomApiClientError(str(cause))


class CitycomApiClient:
    """API client for Citycom MV."""

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize the API client."""
        self._client = CityComMVClient(
            username=username, password=password, session=session
        )

    @property
    def token(self) -> dict[str, Any] | None:
        """The current token, serializable for storage."""
        token = self._client.get_token()
        if not token or not token.access_token:
            return None
        return {"access_token": token.access_token, "expires": token.expires}

    @property
    def token_expires_at(self) -> datetime | None:
        """When the current token expires."""
        return self._client.token_expires_at

    async def async_set_token(self, token: dict[str, Any]) -> None:
        """Use a stored token, if it has not expired."""
        with contextlib.suppress(TokenExpiredError):
            await self._client.load_jwt_token(JWT.from_dict(token))

    async def async_start_login(self, channel: str) -> LoginChallenge | None:
        """Check the password and send a code. None if no code is needed."""
        try:
            return await self._client.login(channel=channel)
        except Exception as err:  # noqa: BLE001
            raise _map_error(err) from err

    async def async_verify_code(self, code: str) -> None:
        """Finish the login with the code that was sent."""
        try:
            await self._client.verify_2fa_code(code)
        except CitycomError as err:
            if err.code in (400, 401, 403):
                raise CitycomApiClientCodeError(str(err)) from err
            raise _map_error(err) from err
        except Exception as err:  # noqa: BLE001
            raise _map_error(err) from err

    async def async_get_customer(self) -> CustomerInformation:
        """Get the customer, with its properties and meters."""
        return await self._call(self._client.get_customer)

    async def async_get_last_reading(self, meter_id: int) -> MeterReadings | None:
        """Get the last reading of a meter."""
        return await self._call(self._client.get_last_meter_reading, str(meter_id))

    async def _call(self, func, *args):
        try:
            return await func(*args)
        except CitycomError as err:
            # A token the server no longer accepts needs a new login, not a
            # new password.
            if err.code == 401:
                raise CitycomApiClientTokenExpiredError(str(err)) from err
            raise _map_error(err) from err
        except Exception as err:  # noqa: BLE001
            raise _map_error(err) from err
