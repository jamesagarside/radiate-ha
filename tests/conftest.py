"""Home Assistant integration tests, run with the Home Assistant test harness.

The fixtures come from `scripts/ha_fixtures.py` in the radiate repository: the
`/api/v1/house` and `/api/v1/state` responses of the demo runtime after about two days,
with a nozzle rating, an override on Bedroom 1 and the Lounge fire switch on, and
`house_people.json`, `/api/v1/house` for the example household with one person linked.
"""

import json
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.radiate.const import CONF_TOKEN, CONF_URL, DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"
URL = "http://radiate.test:8099"
POST_PATHS = (
    "rooms/bedroom_1/setpoint",
    "rooms/lounge/fire",
    "store/boost",
    "mode",
    "settings",
    "ha/persons",
    "outdoor",
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def house() -> dict:
    return json.loads((FIXTURES / "house.json").read_text())


@pytest.fixture
def house_people() -> dict:
    """`/api/v1/house` for a household whose `home_worker` is linked to
    `person.home_worker` in Radiate's setup wizard."""
    return json.loads((FIXTURES / "house_people.json").read_text())


@pytest.fixture
def state() -> dict:
    return json.loads((FIXTURES / "state.json").read_text())


def mock_server(aioclient_mock, house: dict, state: dict) -> None:
    """Register the API on `aioclient_mock`, replacing anything registered before."""
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{URL}/api/v1/house", json=house)
    aioclient_mock.get(f"{URL}/api/v1/state", json=state)
    for path in POST_PATHS:
        aioclient_mock.post(f"{URL}/api/v1/{path}", json={"ok": True})


@pytest.fixture
def radiate_api(aioclient_mock, house, state):
    mock_server(aioclient_mock, house, state)
    return aioclient_mock


async def setup_integration(hass: HomeAssistant, house: dict) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=house["id"], data={CONF_URL: URL, CONF_TOKEN: ""}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def posts(aioclient_mock, persons: bool = False) -> list[tuple[str, dict]]:
    """(path below api/v1/, body) for every POST made so far.

    The report of Home Assistant's person entities (`ha/persons`), sent at setup and
    with every heartbeat, is left out unless `persons` is true.
    """
    prefix = f"{URL}/api/v1/"
    calls = [
        (str(c[1]).removeprefix(prefix), c[2]) for c in aioclient_mock.mock_calls if c[0] == "POST"
    ]
    return [c for c in calls if persons or c[0] != "ha/persons"]
