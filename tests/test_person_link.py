"""Links to `person` entities set in Radiate's setup wizard, and which link wins.

`house_people.json` links `home_worker` to `person.home_worker` on the server. A mapping
in the integration's options wins over it; without one, the server's link is used for
presence, the away sensor's attributes and the away services. The integration also
tells the server which `person` entities exist, so the wizard can offer them.
"""

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.radiate.const import CONF_PEOPLE, DOMAIN

from .conftest import URL, mock_server, posts
from .test_away import person, setup_with


@pytest.fixture
def people_state(state) -> dict:
    away = {
        "everyone": False,
        "frost": False,
        "presence_delay_min": 60,
        "today": "2026-11-18",
        "people": [person("early_riser"), person("home_worker")],
    }
    return {**state, "away": away}


def mock(aioclient_mock, house: dict, state: dict) -> None:
    mock_server(aioclient_mock, house, state)
    for pid in ("early_riser", "home_worker"):
        for path in ("away", "presence"):
            aioclient_mock.post(f"{URL}/api/v1/people/{pid}/{path}", json={"ok": True})


def sent(aioclient_mock, suffix: str) -> list[tuple[str, dict]]:
    return [(p, body) for p, body in posts(aioclient_mock, persons=True) if p.endswith(suffix)]


def away_sensor(hass: HomeAssistant, pid: str):
    return hass.states.get(f"binary_sensor.radiate_{pid}_away")


async def test_the_wizards_link_is_used_without_options(
    hass: HomeAssistant, aioclient_mock, house_people, people_state
):
    mock(aioclient_mock, house_people, people_state)
    hass.states.async_set("person.home_worker", "not_home")
    await setup_with(hass, house_people)
    presence = sent(aioclient_mock, "/presence")
    assert [(p, b["state"]) for p, b in presence] == [("people/home_worker/presence", "not_home")]
    assert away_sensor(hass, "home_worker").attributes["person_entity"] == "person.home_worker"
    assert away_sensor(hass, "early_riser").attributes["person_entity"] is None

    hass.states.async_set("person.home_worker", "home")
    await hass.async_block_till_done()
    assert sent(aioclient_mock, "/presence")[-1] == (
        "people/home_worker/presence",
        {"state": "home", "since": hass.states.get("person.home_worker").last_changed.isoformat()},
    )
    # The services take the linked entity as well as the person ID.
    await hass.services.async_call(
        DOMAIN, "clear_away", {"person": "person.home_worker"}, blocking=True
    )
    assert posts(aioclient_mock)[-1] == ("people/home_worker/away", {"until": None})


async def test_a_mapping_in_the_options_wins(
    hass: HomeAssistant, aioclient_mock, house_people, people_state
):
    mock(aioclient_mock, house_people, people_state)
    hass.states.async_set("person.home_worker", "not_home")
    hass.states.async_set("person.sam", "home")
    await setup_with(hass, house_people, {CONF_PEOPLE: {"home_worker": "person.sam"}})
    presence = sent(aioclient_mock, "/presence")
    assert [(p, b["state"]) for p, b in presence] == [("people/home_worker/presence", "home")]
    assert away_sensor(hass, "home_worker").attributes["person_entity"] == "person.sam"

    hass.states.async_set("person.home_worker", "home")  # no longer the one that counts
    await hass.async_block_till_done()
    assert len(sent(aioclient_mock, "/presence")) == 1
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "clear_away", {"person": "person.home_worker"}, blocking=True
        )
    await hass.services.async_call(DOMAIN, "clear_away", {"person": "person.sam"}, blocking=True)
    assert posts(aioclient_mock)[-1] == ("people/home_worker/away", {"until": None})


async def test_options_flow_shows_the_wizards_link(
    hass: HomeAssistant, aioclient_mock, house_people, people_state
):
    mock(aioclient_mock, house_people, people_state)
    entry = await setup_with(hass, house_people)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    names = result["description_placeholders"]["people"]
    assert names == (
        "early_riser (Early riser), "
        "home_worker (Home worker, linked in Radiate to person.home_worker)"
    )
    # Nothing is copied into the options, so a later change in the wizard still counts.
    assert result["data_schema"]({}) == {}


async def test_person_entities_are_reported_at_setup_and_with_the_heartbeat(
    hass: HomeAssistant, aioclient_mock, house, state
):
    mock_server(aioclient_mock, house, state)
    hass.states.async_set("person.sam", "home", {"friendly_name": "Sam"})
    hass.states.async_set("person.alex", "not_home", {"friendly_name": "Alex"})
    hass.states.async_set("device_tracker.phone", "home")
    await setup_with(hass, house)
    expected = {
        "persons": [
            {"entity_id": "person.alex", "name": "Alex"},
            {"entity_id": "person.sam", "name": "Sam"},
        ]
    }
    assert sent(aioclient_mock, "ha/persons") == [("ha/persons", expected)]

    hass.states.async_set("person.jo", "home")  # no friendly name: the object ID
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=15, seconds=1))
    await hass.async_block_till_done()
    persons = sent(aioclient_mock, "ha/persons")[-1][1]["persons"]
    assert {"entity_id": "person.jo", "name": "jo"} in persons and len(persons) == 3


async def test_a_server_without_the_route_still_gets_presence(
    hass: HomeAssistant, aioclient_mock, house_people, people_state
):
    mock(aioclient_mock, house_people, people_state)
    # Replace the route's answer with the 404 of a server from before it existed.
    aioclient_mock._mocks = [m for m in aioclient_mock._mocks if "ha/persons" not in str(m.url)]
    aioclient_mock.post(f"{URL}/api/v1/ha/persons", status=404, text="not found")
    hass.states.async_set("person.home_worker", "home")
    entry = await setup_with(hass, house_people)
    assert entry.state is ConfigEntryState.LOADED
    assert sent(aioclient_mock, "ha/persons")  # tried, and the 404 was ignored
    assert sent(aioclient_mock, "/presence")[0][0] == "people/home_worker/presence"


async def test_a_link_changed_in_the_wizard_takes_effect_at_the_heartbeat(
    hass: HomeAssistant, aioclient_mock, house_people, people_state
):
    mock(aioclient_mock, house_people, people_state)
    hass.states.async_set("person.alex", "not_home")
    entry = await setup_with(hass, house_people)
    assert away_sensor(hass, "early_riser").attributes["person_entity"] is None

    # Unchanged: no reload.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=15, seconds=1))
    await hass.async_block_till_done()
    assert away_sensor(hass, "early_riser").attributes["person_entity"] is None

    changed = {**house_people, "people": [dict(p) for p in house_people["people"]]}
    changed["people"][0]["ha_person"] = "person.alex"
    mock(aioclient_mock, changed, people_state)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=30, seconds=2))
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert away_sensor(hass, "early_riser").attributes["person_entity"] == "person.alex"
    assert ("people/early_riser/presence", "not_home") in [
        (p, b["state"]) for p, b in sent(aioclient_mock, "/presence")
    ]
