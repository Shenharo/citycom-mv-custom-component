"""Tests for the cost estimate and its sensor."""

from custom_components.citycom_mv_water_meter.pricing import compute_cost

from .test_alerts_history import _setup


def test_cost_without_allowance_is_all_regular():
    assert compute_cost(2.0, regular=10) == 20


def test_cost_splits_at_the_allowance_and_adds_drain_and_fixed():
    cost = compute_cost(
        1.5,
        regular=10,
        over=20,
        drain=1,
        fixed=5,
        allowance_per_person=0.5,
        persons=2,
    )
    # 1.0 m3 regular + 0.5 m3 over + 1.5 m3 drain + fixed
    assert cost == 10 + 10 + 1.5 + 5


def test_over_price_defaults_to_regular():
    assert compute_cost(3.0, regular=10, allowance_per_person=1, persons=1) == 30


async def test_cost_sensor_uses_the_price_options(hass, mock_client, mock_imap):
    options = {
        "price_regular": 10,
        "price_over": 20,
        "price_drain": 1,
        "price_fixed": 5,
        "allowance_per_person": 0.5,
        "persons": 2,
    }
    await _setup(hass, options)

    state = hass.states.get("sensor.water_meter_a_111_cost_this_month_estimate")
    # The mocked month consumption is 1.5 m3.
    assert state.state == "26.5"
    assert state.attributes["device_class"] == "monetary"
    assert state.attributes["unit_of_measurement"] == hass.config.currency


async def test_no_cost_sensor_without_a_price(hass, mock_client, mock_imap):
    await _setup(hass)
    assert hass.states.get("sensor.water_meter_a_111_cost_this_month_estimate") is None
