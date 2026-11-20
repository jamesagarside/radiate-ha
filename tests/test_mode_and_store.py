"""The heating mode select and the hot-water store binary sensors."""

import copy

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .conftest import URL, mock_server, posts, setup_integration

MODE = "select.radiate_heating_mode"
STORE = "binary_sensor.radiate_hot_water_store"
BOOST = "binary_sensor.radiate_hot_water_boost"


def _without(state: dict, *keys: str) -> dict:
    old = copy.deepcopy(state)
    for key in keys:
        old.pop(key)
    return old


async def _refresh(hass: HomeAssistant, entry) -> None:
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()


def _state_reads(aioclient_mock) -> int:
    return sum(
        1 for c in aioclient_mock.mock_calls if c[0] == "GET" and str(c[1]).endswith("/state")
    )


async def test_mode_select_shows_the_server_mode(hass: HomeAssistant, aioclient_mock, house, state):
    mock_server(aioclient_mock, house, state)
    entry = await setup_integration(hass, house)
    mode = hass.states.get(MODE)
    assert mode.state == "auto"  # the fixture's mode
    assert mode.attributes["options"] == ["auto", "frost", "off"]
    entity = er.async_get(hass).async_get(MODE)
    assert entity.unique_id == f"{house['id']}_house_mode"
    assert entity.translation_key == "mode"

    state["mode"] = "frost"
    mock_server(aioclient_mock, house, state)
    await _refresh(hass, entry)
    assert hass.states.get(MODE).state == "frost"

    state["mode"] = "holiday"  # a mode this integration does not know
    mock_server(aioclient_mock, house, state)
    await _refresh(hass, entry)
    assert hass.states.get(MODE).state == STATE_UNKNOWN


@pytest.mark.parametrize("option", ["auto", "frost", "off"])
async def test_selecting_a_mode_posts_it_and_refreshes(
    hass: HomeAssistant, radiate_api, house, option
):
    await setup_integration(hass, house)
    reads = _state_reads(radiate_api)
    await hass.services.async_call(
        "select", "select_option", {"entity_id": MODE, "option": option}, blocking=True
    )
    assert posts(radiate_api) == [("mode", {"mode": option})]
    assert _state_reads(radiate_api) > reads


async def test_selecting_a_mode_reports_a_server_error(
    hass: HomeAssistant, aioclient_mock, house, state
):
    mock_server(aioclient_mock, house, state)
    await setup_integration(hass, house)
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{URL}/api/v1/state", json=state)
    aioclient_mock.post(f"{URL}/api/v1/mode", status=500, text="boom")
    with pytest.raises(HomeAssistantError, match="Radiate"):
        await hass.services.async_call(
            "select", "select_option", {"entity_id": MODE, "option": "off"}, blocking=True
        )


async def test_store_binary_sensors(hass: HomeAssistant, aioclient_mock, house, state):
    mock_server(aioclient_mock, house, state)
    entry = await setup_integration(hass, house)
    store, boost = hass.states.get(STORE), hass.states.get(BOOST)
    # The fixture has the store relay on in a window, with no boost.
    assert store.state == STATE_ON and boost.state == STATE_OFF
    assert "device_class" not in store.attributes
    assert "device_class" not in boost.attributes
    registry = er.async_get(hass)
    assert registry.async_get(STORE).unique_id == f"{house['id']}_house_store"
    assert registry.async_get(BOOST).unique_id == f"{house['id']}_house_store_boost"

    state["store"] = {"relay": True, "boost": True}
    mock_server(aioclient_mock, house, state)
    await _refresh(hass, entry)
    assert hass.states.get(STORE).state == STATE_ON
    assert hass.states.get(BOOST).state == STATE_ON

    state["store"] = {"relay": False, "boost": False}
    mock_server(aioclient_mock, house, state)
    await _refresh(hass, entry)
    assert hass.states.get(STORE).state == STATE_OFF
    assert hass.states.get(BOOST).state == STATE_OFF


async def test_unavailable_when_the_server_stops_reporting(
    hass: HomeAssistant, aioclient_mock, house, state
):
    mock_server(aioclient_mock, house, state)
    entry = await setup_integration(hass, house)

    partial = copy.deepcopy(state)
    partial["store"] = {"relay": True}
    mock_server(aioclient_mock, house, partial)
    await _refresh(hass, entry)
    assert hass.states.get(STORE).state == STATE_ON
    assert hass.states.get(BOOST).state == STATE_UNAVAILABLE

    mock_server(aioclient_mock, house, _without(state, "mode", "store"))
    await _refresh(hass, entry)
    for entity_id in (MODE, STORE, BOOST):
        assert hass.states.get(entity_id).state == STATE_UNAVAILABLE, entity_id

    mock_server(aioclient_mock, house, state)
    await _refresh(hass, entry)
    assert hass.states.get(MODE).state == "auto"
    assert hass.states.get(STORE).state == STATE_ON


async def test_not_created_when_the_server_never_reports(
    hass: HomeAssistant, aioclient_mock, house, state
):
    mock_server(aioclient_mock, house, _without(state, "mode", "store"))
    await setup_integration(hass, house)
    for entity_id in (MODE, STORE, BOOST):
        assert hass.states.get(entity_id) is None, entity_id
    assert hass.states.get("binary_sensor.radiate_boiler_firing") is not None
