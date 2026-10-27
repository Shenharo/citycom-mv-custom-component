"""Tests for error mapping in the API wrapper."""

from citycom_mv_api.models.exceptions import CitycomError, LoginError, TokenExpiredError

from custom_components.citycom_mv_water_meter.api import (
    CitycomApiClientAuthenticationError,
    CitycomApiClientCommunicationError,
    CitycomApiClientError,
    CitycomApiClientTokenExpiredError,
    _map_error,
)


def _wrapped(inner: Exception) -> LoginError:
    """Mimic citycom_mv_api.login.do_login, which wraps unexpected failures."""
    try:
        try:
            raise inner
        except Exception as err:
            raise LoginError(-1, "Failed at first login") from err
    except LoginError as outer:
        return outer


def test_rejected_password_is_auth_error():
    assert isinstance(
        _map_error(CitycomError(400, "Invalid username or password")),
        CitycomApiClientAuthenticationError,
    )


def test_timeout_during_login_is_communication_error():
    assert isinstance(
        _map_error(_wrapped(CitycomError(-1, "time out"))),
        CitycomApiClientCommunicationError,
    )


def test_expired_token():
    assert isinstance(
        _map_error(TokenExpiredError()), CitycomApiClientTokenExpiredError
    )


def test_server_error_is_communication_error():
    assert isinstance(
        _map_error(CitycomError(500, "boom")), CitycomApiClientCommunicationError
    )


def test_unexpected_error_is_generic():
    assert type(_map_error(KeyError("x"))) is CitycomApiClientError
