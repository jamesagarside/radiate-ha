"""Entities and services added for the accounting, override, fire and alert API."""

import copy
import json
from pathlib import Path

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify
from homeassistant.util.yaml import load_yaml

from custom_components.radiate.const import DOMAIN
from custom_components.radiate.select import DEMAND_MODES

from .conftest import URL, mock_server, posts, setup_integration

INTEGRATION = Path(__file__).parents[2] / "custom_components" / DOMAIN

HOUSE_SENSORS = {
    "sensor.radiate_burner_hours_today": "burner_hours_today",
    "sensor.radiate_starts_today": "relay_starts_today",
    "sensor.radiate_oil_used_today": "oil_today",
    "sensor.radiate_heat_delivered_today": "heat_today",
    "sensor.radiate_balance_score_yesterday": "balance_score_yesterday",
    "sensor.radiate_short_cycle_extra_off_time": "short_cycle_extra_off",
    "sensor.radiate_alerts": "alerts",
    "sensor.radiate_pooled_demand": "pooled_demand",
    "select.radiate_demand_mode": "demand_mode",
}


def _old_server(state: dict) -> dict:
    """The state shape before accounting, overrides, valve checks, alert codes and settings."""
    old = copy.deepcopy(state)
    for key in ("accounting", "alert_details", "settings"):
        old.pop(key)
    for key in ("short_cycle", "min_off_s", "pooled_demand_min"):
        old["boiler"].pop(key)
    for room in old["rooms"]:
        for key in ("override", "fire_switch", "valve"):
            room.pop(key, None)
    return old


async def _refresh(hass: HomeAssistant, entry) -> None:
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()


async def test_accounting_sensors(hass: HomeAssistant, radiate_api, house, state):
    entry = await setup_integration(hass, house)
    today, yesterday = state["accounting"]["today"], state["accounting"]["yesterday"]

    hours = hass.states.get("sensor.radiate_burner_hours_today")
    assert float(hours.state) == today["burner_hours"]
    assert hours.attributes["unit_of_measurement"] == "h"
    assert hours.attributes["device_class"] == SensorDeviceClass.DURATION
    assert hours.attributes["state_class"] == SensorStateClass.TOTAL_INCREASING
    assert hours.attributes["basis"] == "relay"

    starts = hass.states.get("sensor.radiate_starts_today")
    assert int(starts.state) == today["starts"]
    assert starts.attributes["state_class"] == SensorStateClass.TOTAL_INCREASING
    assert starts.attributes["max_starts_in_hour"] == today["max_starts_in_hour"]

    oil = hass.states.get("sensor.radiate_oil_used_today")
    assert float(oil.state) == today["litres"]
    assert oil.attributes["unit_of_measurement"] == "L"
    assert oil.attributes["device_class"] == SensorDeviceClass.VOLUME
    assert oil.attributes["state_class"] == SensorStateClass.TOTAL_INCREASING

    heat = hass.states.get("sensor.radiate_heat_delivered_today")
    assert float(heat.state) == today["kwh"]
    assert heat.attributes["unit_of_measurement"] == "kWh"
    assert heat.attributes["device_class"] == SensorDeviceClass.ENERGY
    assert heat.attributes["state_class"] == SensorStateClass.TOTAL_INCREASING

    score = hass.states.get("sensor.radiate_balance_score_yesterday")
    assert float(score.state) == yesterday["balance"]["score"]
    assert score.attributes["state_class"] == SensorStateClass.MEASUREMENT
    assert score.attributes["arrival_spread_min"] == yesterday["balance"]["arrival_spread_min"]
    assert score.attributes["starts_measured"] == yesterday["balance"]["starts_measured"]

    ents = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    ids = {e.unique_id for e in ents}
    for key in HOUSE_SENSORS.values():
        assert f"{house['id']}_house_{key}" in ids


async def test_litres_only_with_a_nozzle_rating(hass: HomeAssistant, aioclient_mock, house, state):
    state["accounting"]["today"]["litres"] = state["accounting"]["today"]["kwh"] = None
    mock_server(aioclient_mock, house, state)
    await setup_integration(hass, house)
    assert hass.states.get("sensor.radiate_burner_hours_today") is not None
    assert hass.states.get("sensor.radiate_oil_used_today") is None
    assert hass.states.get("sensor.radiate_heat_delivered_today") is None


async def test_no_yesterday_yet_is_unknown(hass: HomeAssistant, aioclient_mock, house, state):
    state["accounting"]["yesterday"] = None
    mock_server(aioclient_mock, house, state)
    await setup_integration(hass, house)
    assert hass.states.get("sensor.radiate_balance_score_yesterday").state == "unknown"


async def test_short_cycle_sensor(hass: HomeAssistant, aioclient_mock, house, state):
    mock_server(aioclient_mock, house, state)
    entry = await setup_integration(hass, house)
    sc = hass.states.get("sensor.radiate_short_cycle_extra_off_time")
    assert sc.state == "0"
    assert sc.attributes["unit_of_measurement"] == "min"
    assert sc.attributes["min_off_min"] == 10
    assert sc.attributes["ends_in_h"] is None

    state["boiler"]["short_cycle"] = {"extra_off_min": 5, "ends_in_h": 23.5}
    state["boiler"]["min_off_s"] = 900
    mock_server(aioclient_mock, house, state)
    await _refresh(hass, entry)
    sc = hass.states.get("sensor.radiate_short_cycle_extra_off_time")
    assert sc.state == "5"
    assert sc.attributes["ends_in_h"] == 23.5
    assert sc.attributes["min_off_min"] == 15


async def test_alerts_sensor(hass: HomeAssistant, aioclient_mock, house, state):
    mock_server(aioclient_mock, house, state)
    entry = await setup_integration(hass, house)
    alerts = hass.states.get("sensor.radiate_alerts")
    assert alerts.state == "0" and alerts.attributes["alerts"] == []

    message = "Bedroom 1 radiator not warming: check the valve"
    state["alerts"] = [message]
    state["alert_details"] = [{"code": "valve.stuck", "message": message, "room_id": "bedroom_1"}]
    mock_server(aioclient_mock, house, state)
    await _refresh(hass, entry)
    alerts = hass.states.get("sensor.radiate_alerts")
    assert alerts.state == "1"
    assert alerts.attributes["alerts"] == state["alert_details"]


async def test_demand_mode_select(hass: HomeAssistant, aioclient_mock, house, state):
    mock_server(aioclient_mock, house, state)
    entry = await setup_integration(hass, house)
    select = hass.states.get("select.radiate_demand_mode")
    assert select.state == "eco"
    assert select.attributes["options"] == ["eco", "comfort"]
    assert select.attributes["default_mode"] == "eco"
    entity = er.async_get(hass).async_get("select.radiate_demand_mode")
    assert entity.unique_id == f"{house['id']}_house_demand_mode"
    assert entity.entity_category is None  # a control people use, not a diagnostic

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.radiate_demand_mode", "option": "comfort"},
        blocking=True,
    )
    assert posts(aioclient_mock)[-1] == ("settings", {"demand_mode": "comfort"})

    # Choosing the configured default follows the configuration file again.
    state["settings"]["demand_mode"] = "comfort"
    mock_server(aioclient_mock, house, state)
    await _refresh(hass, entry)
    assert hass.states.get("select.radiate_demand_mode").state == "comfort"
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.radiate_demand_mode", "option": "eco"},
        blocking=True,
    )
    assert posts(aioclient_mock)[-1] == ("settings", {"demand_mode": None})


async def test_demand_mode_select_reports_server_errors(
    hass: HomeAssistant, aioclient_mock, house, state
):
    mock_server(aioclient_mock, house, state)
    await setup_integration(hass, house)
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{URL}/api/v1/state", json=state)
    aioclient_mock.post(f"{URL}/api/v1/settings", status=400, text="bad demand_mode")
    with pytest.raises(HomeAssistantError, match="HTTP 400"):
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": "select.radiate_demand_mode", "option": "comfort"},
            blocking=True,
        )


async def test_pooled_demand_sensor(hass: HomeAssistant, radiate_api, house, state):
    await setup_integration(hass, house)
    pooled = hass.states.get("sensor.radiate_pooled_demand")
    assert float(pooled.state) == state["boiler"]["pooled_demand_min"]
    assert pooled.attributes["unit_of_measurement"] == "min"
    assert pooled.attributes["device_class"] == SensorDeviceClass.DURATION
    assert pooled.attributes["state_class"] == SensorStateClass.MEASUREMENT
    entity = er.async_get(hass).async_get("sensor.radiate_pooled_demand")
    assert entity.unique_id == f"{house['id']}_house_pooled_demand"


async def test_stuck_valve_binary_sensor(hass: HomeAssistant, aioclient_mock, house, state):
    mock_server(aioclient_mock, house, state)
    entry = await setup_integration(hass, house)
    valve = hass.states.get("binary_sensor.bedroom_1_stuck_valve")
    assert valve.state == STATE_OFF
    assert valve.attributes["device_class"] == "problem"
    assert valve.attributes["misses"] == 0
    assert hass.states.get("binary_sensor.stairs_stuck_valve") is None  # not controllable
    entity = er.async_get(hass).async_get("binary_sensor.bedroom_1_stuck_valve")
    assert entity.unique_id == f"{house['id']}_bedroom_1_valve_untrusted"

    room = next(r for r in state["rooms"] if r["id"] == "bedroom_1")
    room["valve"] = {"untrusted": True, "misses": 3}
    mock_server(aioclient_mock, house, state)
    await _refresh(hass, entry)
    valve = hass.states.get("binary_sensor.bedroom_1_stuck_valve")
    assert valve.state == STATE_ON and valve.attributes["misses"] == 3


async def test_learning_sensor(hass: HomeAssistant, radiate_api, house, state):
    await setup_integration(hass, house)
    for room in state["rooms"]:
        if not room.get("valve"):
            continue  # not controllable
        sensor = hass.states.get(f"sensor.{slugify(room['name'])}_learning")
        assert sensor.state == (room["learning"] or "active")


async def test_climate_override_attributes(hass: HomeAssistant, radiate_api, house, state):
    await setup_integration(hass, house)
    bed = next(r for r in state["rooms"] if r["id"] == "bedroom_1")
    attrs = hass.states.get("climate.bedroom_1").attributes
    assert attrs["override_setpoint"] == bed["override"]["setpoint"]
    assert attrs["override_until"] == "duration"
    assert attrs["override_expires_in_min"] == bed["override"]["expires_in_min"]
    attrs = hass.states.get("climate.bedroom_2").attributes
    assert attrs["override_setpoint"] is None and attrs["override_until"] is None


async def test_fire_switch(hass: HomeAssistant, radiate_api, house):
    await setup_integration(hass, house)
    switch = hass.states.get("switch.lounge_fire_lit")
    assert switch.state == STATE_ON  # the fixture has the Lounge fire switch on
    assert "assumed_state" not in switch.attributes
    assert hass.states.get("binary_sensor.lounge_fire_detected").state == STATE_ON
    assert hass.states.get("switch.kitchen_fire_lit") is None  # the Aga is not episodic
    entity = er.async_get(hass).async_get("switch.lounge_fire_lit")
    assert entity.unique_id == f"{house['id']}_lounge_fire_switch"

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.lounge_fire_lit"}, blocking=True
    )
    assert posts(radiate_api)[-1] == ("rooms/lounge/fire", {"lit": False})
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.lounge_fire_lit"}, blocking=True
    )
    assert posts(radiate_api)[-1] == ("rooms/lounge/fire", {"lit": True})


@pytest.mark.parametrize(
    ("data", "body"),
    [
        ({"temperature": 22}, {"setpoint": 22.0}),
        ({"temperature": 22, "duration_min": 90}, {"setpoint": 22.0, "duration_min": 90}),
        (
            {"temperature": 19.5, "until": "duration", "duration_min": 30},
            {"setpoint": 19.5, "until": "duration", "duration_min": 30},
        ),
        ({"temperature": 18, "until": "cleared"}, {"setpoint": 18.0, "until": "cleared"}),
        ({"temperature": 18, "until": "next_change"}, {"setpoint": 18.0, "until": "next_change"}),
    ],
)
async def test_set_override_service(hass: HomeAssistant, radiate_api, house, data, body):
    await setup_integration(hass, house)
    await hass.services.async_call(
        DOMAIN, "set_override", {"entity_id": "climate.bedroom_1", **data}, blocking=True
    )
    assert posts(radiate_api)[-1] == ("rooms/bedroom_1/setpoint", body)


@pytest.mark.parametrize(
    ("data", "key"),
    [
        ({"temperature": 22, "until": "duration"}, "duration_needed"),
        ({"temperature": 22, "until": "cleared", "duration_min": 30}, "duration_conflict"),
    ],
)
async def test_set_override_rejects_mixed_options(
    hass: HomeAssistant, radiate_api, house, data, key
):
    await setup_integration(hass, house)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "set_override", {"entity_id": "climate.bedroom_1", **data}, blocking=True
        )
    assert err.value.translation_key == key
    assert not posts(radiate_api)


async def test_set_override_rejects_out_of_range(hass: HomeAssistant, radiate_api, house):
    await setup_integration(hass, house)
    with pytest.raises(Exception, match="value must be at most"):
        await hass.services.async_call(
            DOMAIN,
            "set_override",
            {"entity_id": "climate.bedroom_1", "temperature": 35},
            blocking=True,
        )


async def test_clear_override_service(hass: HomeAssistant, radiate_api, house):
    await setup_integration(hass, house)
    await hass.services.async_call(
        DOMAIN, "clear_override", {"entity_id": "climate.bedroom_1"}, blocking=True
    )
    assert posts(radiate_api)[-1] == ("rooms/bedroom_1/setpoint", {"setpoint": None})


def test_services_are_declared_and_translated():
    services = load_yaml(INTEGRATION / "services.yaml")
    strings = json.loads((INTEGRATION / "strings.json").read_text())
    assert json.loads((INTEGRATION / "translations" / "en.json").read_text()) == strings
    assert set(services) == {"boost_store", "set_mode", "set_override", "clear_override"}
    assert set(services) == set(strings["services"])
    for name, service in services.items():
        fields = (service or {}).get("fields", {})
        assert set(fields) == set(strings["services"][name].get("fields", {})), name
    until = services["set_override"]["fields"]["until"]["selector"]["select"]
    assert set(until["options"]) == set(strings["selector"][until["translation_key"]]["options"])
    demand = strings["entity"]["select"]["demand_mode"]["state"]
    assert list(demand) == DEMAND_MODES


async def test_older_server_without_new_keys(hass: HomeAssistant, aioclient_mock, house, state):
    mock_server(aioclient_mock, house, _old_server(state))
    entry = await setup_integration(hass, house)
    for entity_id in HOUSE_SENSORS:
        if entity_id != "sensor.radiate_alerts":
            assert hass.states.get(entity_id) is None, entity_id
    assert hass.states.get("binary_sensor.bedroom_1_stuck_valve") is None
    # Alerts fall back to messages without codes.
    alerts = hass.states.get("sensor.radiate_alerts")
    assert alerts.state == "0"
    attrs = hass.states.get("climate.bedroom_1").attributes
    assert attrs["override_setpoint"] is None
    # Without `fire_switch` the switch shows the last value set from Home Assistant.
    switch = hass.states.get("switch.lounge_fire_lit")
    assert switch.state == STATE_OFF and switch.attributes["assumed_state"] is True
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.lounge_fire_lit"}, blocking=True
    )
    assert hass.states.get("switch.lounge_fire_lit").state == STATE_ON

    old = _old_server(state)
    old["alerts"] = ["No TRVs reachable"]
    mock_server(aioclient_mock, house, old)
    await _refresh(hass, entry)
    assert hass.states.get("sensor.radiate_alerts").attributes["alerts"] == [
        {"code": None, "message": "No TRVs reachable", "room_id": None}
    ]


async def test_keys_that_disappear_make_entities_unavailable(
    hass: HomeAssistant, aioclient_mock, house, state
):
    mock_server(aioclient_mock, house, state)
    entry = await setup_integration(hass, house)
    assert hass.states.get("sensor.radiate_burner_hours_today").state != STATE_UNAVAILABLE

    mock_server(aioclient_mock, house, _old_server(state))
    await _refresh(hass, entry)
    for entity_id in HOUSE_SENSORS:
        if entity_id != "sensor.radiate_alerts":
            assert hass.states.get(entity_id).state == STATE_UNAVAILABLE, entity_id
    assert hass.states.get("binary_sensor.bedroom_1_stuck_valve").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.radiate_alerts").state == "0"
