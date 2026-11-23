"""Away: the options flow, presence reporting, away entities and services."""

from datetime import datetime, timedelta

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.radiate.const import CONF_PEOPLE, CONF_TOKEN, CONF_URL, DOMAIN
from custom_components.radiate.presence import presence_of

from .conftest import URL, mock_server, posts, setup_integration

PEOPLE = [
    {"id": "early_riser", "name": "Early riser"},
    {"id": "home_worker", "name": "Home worker"},
]


def person(pid: str, **over) -> dict:
    name = next(p["name"] for p in PEOPLE if p["id"] == pid)
    view = {"id": pid, "name": name, "away": False, "reason": None, "until": None}
    return {**view, "presence": None, **over}


@pytest.fixture
def household_house(house) -> dict:
    return {**house, "people": PEOPLE}


@pytest.fixture
def household_state(state) -> dict:
    away = {
        "everyone": False,
        "frost": False,
        "presence_delay_min": 60,
        "today": "2026-11-18",
        "people": [
            person("early_riser"),
            person(
                "home_worker",
                away=True,
                reason="away_until",
                until="2026-11-20T18:00+00:00",
            ),
        ],
    }
    return {**state, "away": away}


def mock_people(aioclient_mock, house: dict, state: dict) -> None:
    mock_server(aioclient_mock, house, state)
    for p in PEOPLE:
        for path in ("away", "presence"):
            aioclient_mock.post(f"{URL}/api/v1/people/{p['id']}/{path}", json={"ok": True})


async def setup_with(hass: HomeAssistant, house: dict, options: dict | None = None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=house["id"],
        data={CONF_URL: URL, CONF_TOKEN: ""},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def presence_posts(aioclient_mock) -> list[tuple[str, dict]]:
    return [(path, body) for path, body in posts(aioclient_mock) if path.endswith("/presence")]


def test_presence_of():
    class S:
        def __init__(self, state):
            self.state = state

    assert presence_of(None) is None
    assert presence_of(S("unknown")) is None
    assert presence_of(S("unavailable")) is None
    assert presence_of(S("home")) == "home"
    assert presence_of(S("not_home")) == "not_home"
    assert presence_of(S("Work")) == "not_home"  # a zone: not at home


async def test_away_entity_per_person(
    hass: HomeAssistant, aioclient_mock, household_house, household_state
):
    mock_people(aioclient_mock, household_house, household_state)
    await setup_with(hass, household_house)
    early = hass.states.get("binary_sensor.radiate_early_riser_away")
    assert early.state == STATE_OFF
    worker = hass.states.get("binary_sensor.radiate_home_worker_away")
    assert worker.state == STATE_ON
    assert worker.attributes["away_until"] == "2026-11-20T18:00+00:00"
    assert worker.attributes["reason"] == "away_until"
    assert worker.attributes["person_id"] == "home_worker"
    assert worker.attributes["presence"] is None
    assert worker.attributes["presence_stale"] is None


async def test_away_entity_shows_stale_presence(
    hass: HomeAssistant, aioclient_mock, household_house, household_state
):
    stale = {"state": "not_home", "since": "2026-11-18T05:00+00:00", "stale": True}
    people = [person("early_riser", presence=stale), person("home_worker")]
    state = {**household_state, "away": {**household_state["away"], "people": people}}
    mock_people(aioclient_mock, household_house, state)
    await setup_with(hass, household_house, {CONF_PEOPLE: {"early_riser": "person.alex"}})
    early = hass.states.get("binary_sensor.radiate_early_riser_away")
    assert early.state == STATE_OFF
    assert early.attributes["presence"] == "not_home"
    assert early.attributes["presence_stale"] is True


async def test_no_away_entities_without_people(hass: HomeAssistant, radiate_api, house):
    await setup_integration(hass, house)
    assert hass.states.async_entity_ids("binary_sensor") and not [
        e for e in hass.states.async_entity_ids("binary_sensor") if e.endswith("_away")
    ]


async def test_away_entity_unavailable_when_person_missing(
    hass: HomeAssistant, aioclient_mock, household_house, household_state
):
    mock_people(aioclient_mock, household_house, household_state)
    entry = await setup_with(hass, household_house)
    gone = {**household_state, "away": {**household_state["away"], "people": []}}
    mock_people(aioclient_mock, household_house, gone)
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.radiate_early_riser_away").state == STATE_UNAVAILABLE


async def test_options_flow_maps_people(
    hass: HomeAssistant, aioclient_mock, household_house, household_state
):
    mock_people(aioclient_mock, household_house, household_state)
    entry = await setup_with(hass, household_house)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert set(result["data_schema"].schema) == {"early_riser", "home_worker"}
    assert "early_riser (Early riser)" in result["description_placeholders"]["people"]
    hass.states.async_set("person.alex", "home")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"early_riser": "person.alex"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {CONF_PEOPLE: {"early_riser": "person.alex"}}
    # The entry reloads and reports the mapped person's presence.
    sent = [(p, b["state"]) for p, b in presence_posts(aioclient_mock)]
    assert sent == [("people/early_riser/presence", "home")]


async def test_options_flow_without_people(hass: HomeAssistant, radiate_api, house):
    entry = await setup_integration(hass, house)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_people"


async def test_presence_reported_on_setup_and_on_change(
    hass: HomeAssistant, aioclient_mock, household_house, household_state
):
    mock_people(aioclient_mock, household_house, household_state)
    hass.states.async_set("person.alex", "not_home")
    hass.states.async_set("person.sam", "unknown")
    options = {CONF_PEOPLE: {"early_riser": "person.alex", "home_worker": "person.sam"}}
    await setup_with(hass, household_house, options)
    sent = presence_posts(aioclient_mock)
    assert [p for p, _ in sent] == ["people/early_riser/presence"]  # unknown is not sent
    since = hass.states.get("person.alex").last_changed
    assert sent[0][1] == {"state": "not_home", "since": since.isoformat()}

    hass.states.async_set("person.alex", "Work")  # another zone: still not home
    await hass.async_block_till_done()
    assert len(presence_posts(aioclient_mock)) == 1
    hass.states.async_set("person.alex", "home")
    hass.states.async_set("person.sam", "unavailable")
    await hass.async_block_till_done()
    sent = presence_posts(aioclient_mock)
    assert [(p, b["state"]) for p, b in sent[1:]] == [("people/early_riser/presence", "home")]
    hass.states.async_set("person.sam", "home")
    await hass.async_block_till_done()
    assert presence_posts(aioclient_mock)[-1][0] == "people/home_worker/presence"


async def test_presence_heartbeat_every_15_minutes(
    hass: HomeAssistant, aioclient_mock, household_house, household_state
):
    mock_people(aioclient_mock, household_house, household_state)
    hass.states.async_set("person.alex", "not_home")
    hass.states.async_set("person.sam", "unknown")
    options = {CONF_PEOPLE: {"early_riser": "person.alex", "home_worker": "person.sam"}}
    await setup_with(hass, household_house, options)
    since = hass.states.get("person.alex").last_changed.isoformat()
    assert len(presence_posts(aioclient_mock)) == 1

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=14))
    await hass.async_block_till_done()
    assert len(presence_posts(aioclient_mock)) == 1
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=15, seconds=1))
    await hass.async_block_till_done()
    sent = presence_posts(aioclient_mock)
    # The same state with its original change time; unknown is still not sent.
    assert sent[1:] == [("people/early_riser/presence", {"state": "not_home", "since": since})]

    hass.states.async_set("person.sam", "home")
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=30, seconds=2))
    await hass.async_block_till_done()
    assert {p for p, _ in presence_posts(aioclient_mock)[-2:]} == {
        "people/early_riser/presence",
        "people/home_worker/presence",
    }


async def test_presence_carries_what_the_trackers_say(
    hass: HomeAssistant, aioclient_mock, household_house, household_state
):
    mock_people(aioclient_mock, household_house, household_state)
    hass.states.async_set(
        "device_tracker.phone", "not_home", {"source_type": "gps", "battery_level": 64}
    )
    hass.states.async_set("device_tracker.wifi", "not_home", {"source_type": "router"})
    trackers = ["device_tracker.phone", "device_tracker.wifi"]
    hass.states.async_set(
        "person.alex",
        "not_home",
        {"device_trackers": trackers, "source": "device_tracker.phone"},
    )
    await setup_with(hass, household_house, {CONF_PEOPLE: {"early_riser": "person.alex"}})
    (sent,) = presence_posts(aioclient_mock)
    newest = hass.states.get("device_tracker.wifi").last_reported
    assert sent[1]["evidence_at"] == newest.isoformat()
    assert sent[1]["source_type"] == "gps"  # the tracker the person follows
    assert sent[1]["battery"] == 64

    # The phone goes flat: its person stays not home and nothing reports. The heartbeat
    # repeats the state, with the trackers' last report unchanged, so the server can
    # tell the evidence is old.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=15, seconds=1))
    await hass.async_block_till_done()
    beat = presence_posts(aioclient_mock)[-1][1]
    assert beat["state"] == "not_home" and beat["evidence_at"] == newest.isoformat()


async def test_presence_without_trackers_sends_what_it_always_did(
    hass: HomeAssistant, aioclient_mock, household_house, household_state
):
    mock_people(aioclient_mock, household_house, household_state)
    hass.states.async_set("person.alex", "home", {"device_trackers": ["device_tracker.gone"]})
    await setup_with(hass, household_house, {CONF_PEOPLE: {"early_riser": "person.alex"}})
    (sent,) = presence_posts(aioclient_mock)
    assert set(sent[1]) == {"state", "since"}


async def test_away_entity_shows_why_presence_counts_as_home(
    hass: HomeAssistant, aioclient_mock, household_house, household_state
):
    why = "No report from their phone or tracker since 10:17, so counted as home."
    presence = {"state": "not_home", "since": "2026-11-18T10:17+00:00", "stale": False}
    presence |= {"uncertain": "evidence_old", "why": why}
    people = [person("early_riser", presence=presence), person("home_worker")]
    state = {**household_state, "away": {**household_state["away"], "people": people}}
    mock_people(aioclient_mock, household_house, state)
    await setup_with(hass, household_house)
    early = hass.states.get("binary_sensor.radiate_early_riser_away")
    assert early.state == STATE_OFF and early.attributes["presence_why"] == why


async def test_unmapped_people_have_their_presence_forgotten(
    hass: HomeAssistant, aioclient_mock, household_house, household_state
):
    stale = {"state": "not_home", "since": "2026-11-18T05:00+00:00"}
    people = [person("early_riser", presence=stale), person("home_worker")]
    state = {**household_state, "away": {**household_state["away"], "people": people}}
    mock_people(aioclient_mock, household_house, state)
    await setup_with(hass, household_house)
    assert presence_posts(aioclient_mock) == [("people/early_riser/presence", {"state": None})]


async def test_set_and_clear_away_services(
    hass: HomeAssistant, aioclient_mock, household_house, household_state
):
    mock_people(aioclient_mock, household_house, household_state)
    options = {CONF_PEOPLE: {"home_worker": "person.sam"}}
    await setup_with(hass, household_house, options)
    await hass.services.async_call(
        DOMAIN,
        "set_away",
        {"person": "early_riser", "until": "2026-11-24 18:00:00"},
        blocking=True,
    )
    path, body = posts(aioclient_mock)[-1]
    assert path == "people/early_riser/away"
    until = datetime(2026, 11, 24, 18, tzinfo=dt_util.get_default_time_zone())
    assert body == {"until": until.isoformat()}
    # A mapped person entity works as well as the Radiate person id.
    await hass.services.async_call(DOMAIN, "clear_away", {"person": "person.sam"}, blocking=True)
    assert posts(aioclient_mock)[-1] == ("people/home_worker/away", {"until": None})
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "clear_away", {"person": "nobody"}, blocking=True)
