"""Outdoor temperature: the options flow, reading the entity, and reporting it."""

from datetime import timedelta

import pytest
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.radiate.const import CONF_OUTDOOR, CONF_PEOPLE

from .conftest import URL, mock_server, posts, setup_integration
from .test_away import setup_with

WEATHER = "weather.forecast_home"
GARDEN = "sensor.garden_temperature"


def outdoor_posts(aioclient_mock) -> list[dict]:
    return [body for path, body in posts(aioclient_mock) if path == "outdoor"]


def weather(hass: HomeAssistant, temperature, unit: str = UnitOfTemperature.CELSIUS, **extra):
    attrs = {"temperature": temperature, "temperature_unit": unit, **extra}
    hass.states.async_set(WEATHER, "cloudy", attrs)


def garden(hass: HomeAssistant, value, unit: str = UnitOfTemperature.CELSIUS):
    attrs = {"device_class": "temperature", "unit_of_measurement": unit}
    hass.states.async_set(GARDEN, value, attrs)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (State(WEATHER, "rainy", {"temperature": 7.4, "temperature_unit": "°C"}), 7.4),
        (State(WEATHER, "rainy", {"temperature": 41, "temperature_unit": "°F"}), 5.0),
        (State(WEATHER, "rainy", {}), None),
        (State(WEATHER, "unavailable", {"temperature": 7}), None),
        (State(GARDEN, "3.25", {"unit_of_measurement": "°C"}), 3.25),
        (State(GARDEN, "50", {"unit_of_measurement": "°F"}), 10.0),
        (State(GARDEN, "4"), 4.0),
        (State(GARDEN, "unknown"), None),
        (State(GARDEN, "warm"), None),
        (State(GARDEN, "nan"), None),
        (None, None),
    ],
)
def test_outdoor_temperature(state, expected):
    from custom_components.radiate.outdoor import outdoor_temperature

    assert outdoor_temperature(state) == expected


async def test_no_entity_posts_nothing(hass: HomeAssistant, radiate_api, house):
    await setup_integration(hass, house)
    assert outdoor_posts(radiate_api) == []


async def test_weather_entity_reported_at_setup(hass: HomeAssistant, radiate_api, house):
    weather(hass, 6.5, humidity=90)
    await setup_with(hass, house, {CONF_OUTDOOR: WEATHER})
    state = hass.states.get(WEATHER)
    assert outdoor_posts(radiate_api) == [
        {
            "temperature_c": 6.5,
            "measured_at": state.last_reported.isoformat(),
            "source": WEATHER,
        }
    ]


async def test_reported_on_change_but_not_for_other_attributes(
    hass: HomeAssistant, radiate_api, house
):
    weather(hass, 6.5)
    await setup_with(hass, house, {CONF_OUTDOOR: WEATHER})
    weather(hass, 6.5, humidity=80)  # only another attribute changed
    await hass.async_block_till_done()
    assert len(outdoor_posts(radiate_api)) == 1
    weather(hass, 5.0)
    await hass.async_block_till_done()
    assert [b["temperature_c"] for b in outdoor_posts(radiate_api)] == [6.5, 5.0]
    hass.states.async_set(WEATHER, "unavailable", {})
    await hass.async_block_till_done()
    assert len(outdoor_posts(radiate_api)) == 2  # unavailable is not sent


async def test_sensor_entity_in_fahrenheit(hass: HomeAssistant, radiate_api, house):
    garden(hass, "41", UnitOfTemperature.FAHRENHEIT)
    await setup_with(hass, house, {CONF_OUTDOOR: GARDEN})
    (body,) = outdoor_posts(radiate_api)
    assert body["temperature_c"] == 5.0 and body["source"] == GARDEN


async def test_heartbeat_every_15_minutes_with_last_reported(
    hass: HomeAssistant, radiate_api, house
):
    garden(hass, "3.0")
    await setup_with(hass, house, {CONF_OUTDOOR: GARDEN})
    assert len(outdoor_posts(radiate_api)) == 1
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=14))
    await hass.async_block_till_done()
    assert len(outdoor_posts(radiate_api)) == 1
    # The sensor reports the same value again: no state change, but last_reported moves.
    garden(hass, "3.0")
    await hass.async_block_till_done()
    assert len(outdoor_posts(radiate_api)) == 1
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=15, seconds=1))
    await hass.async_block_till_done()
    sent = outdoor_posts(radiate_api)
    assert len(sent) == 2
    assert sent[1]["measured_at"] == hass.states.get(GARDEN).last_reported.isoformat()
    assert sent[1]["measured_at"] != sent[0]["measured_at"]


def test_measured_at_is_last_reported_and_last_updated_only_without_it():
    from custom_components.radiate.outdoor import measured_at

    state = State(GARDEN, "3.0")
    reported = state.last_updated + timedelta(minutes=20)
    state = State(GARDEN, "3.0", last_updated=state.last_updated, last_reported=reported)
    assert measured_at(state) == reported != state.last_updated

    class OlderState:  # Home Assistant before 2024.3 had no last_reported
        last_updated = state.last_updated

    assert measured_at(OlderState()) == state.last_updated


async def test_cleared_option_forgets_a_reading_an_entity_posted(
    hass: HomeAssistant, aioclient_mock, house, state
):
    reading = {"temperature_c": 6.5, "source": WEATHER, "measured_at": "2026-11-18T05:40+00:00"}
    with_reading = {
        **state,
        "outdoor_reading": {"setting": "home_assistant", "home_assistant": reading},
    }
    mock_server(aioclient_mock, house, with_reading)
    await setup_integration(hass, house)
    assert outdoor_posts(aioclient_mock) == [{"temperature_c": None}]


async def test_a_reading_from_elsewhere_is_left_alone(
    hass: HomeAssistant, aioclient_mock, house, state
):
    reading = {"temperature_c": 6.5, "source": "my_script", "measured_at": "2026-11-18T05:40+00:00"}
    with_reading = {
        **state,
        "outdoor_reading": {"setting": "home_assistant", "home_assistant": reading},
    }
    mock_server(aioclient_mock, house, with_reading)
    await setup_integration(hass, house)
    assert outdoor_posts(aioclient_mock) == []


async def test_an_older_server_without_the_route_does_not_break_setup(
    hass: HomeAssistant, aioclient_mock, house, state, caplog
):
    mock_server(aioclient_mock, house, state)
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{URL}/api/v1/house", json=house)
    aioclient_mock.get(f"{URL}/api/v1/state", json=state)
    aioclient_mock.post(f"{URL}/api/v1/ha/persons", json={"ok": True})
    aioclient_mock.post(f"{URL}/api/v1/outdoor", status=404, text="not found")
    garden(hass, "3.0")
    entry = await setup_with(hass, house, {CONF_OUTDOOR: GARDEN})
    assert entry.state.value == "loaded"
    assert "could not report the outdoor temperature" in caplog.text


async def test_options_flow_sets_and_clears_the_outdoor_entity(
    hass: HomeAssistant, radiate_api, house
):
    weather(hass, 6.5)
    entry = await setup_integration(hass, house)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_OUTDOOR: WEATHER}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {CONF_PEOPLE: {}, CONF_OUTDOOR: WEATHER}
    # The entry reloads and reports the entity.
    assert [b["source"] for b in outdoor_posts(radiate_api)] == [WEATHER]

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert entry.options == {CONF_PEOPLE: {}}
