from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.radiate.const import CONF_URL, DOMAIN

from .conftest import URL, posts, setup_integration


async def test_setup_creates_entities(hass: HomeAssistant, radiate_api, house, state):
    entry = await setup_integration(hass, house)
    assert entry.state is ConfigEntryState.LOADED
    ents = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    domains = {e.domain for e in ents}
    assert domains == {"climate", "select", "sensor", "binary_sensor", "switch"}
    climates = [e for e in ents if e.domain == "climate"]
    assert len(climates) == 8  # stairs bypass radiator is not controllable
    # Unique IDs kept from earlier versions.
    fire = [e for e in ents if e.domain == "binary_sensor" and e.unique_id.endswith("lounge_fire")]
    assert len(fire) == 1
    assert f"{house['id']}_bedroom_1_climate" in {e.unique_id for e in climates}

    bed = next(r for r in state["rooms"] if r["id"] == "bedroom_1")
    climate = hass.states.get("climate.bedroom_1")
    assert climate is not None
    assert climate.attributes["current_temperature"] == bed["temperature"]
    assert climate.attributes["opening_limit"] == bed["opening"]


async def test_set_temperature_calls_server(hass: HomeAssistant, radiate_api, house):
    await setup_integration(hass, house)
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": "climate.bedroom_1", "temperature": 21.5},
        blocking=True,
    )
    # No `until`: the server holds it until the room's next scheduled change.
    assert posts(radiate_api)[-1] == ("rooms/bedroom_1/setpoint", {"setpoint": 21.5})


async def test_services(hass: HomeAssistant, radiate_api, house):
    await setup_integration(hass, house)
    await hass.services.async_call(DOMAIN, "boost_store", {"minutes": 30}, blocking=True)
    await hass.services.async_call(DOMAIN, "set_mode", {"mode": "frost"}, blocking=True)
    bodies = [body for _, body in posts(radiate_api)]
    assert {"minutes": 30} in bodies and {"mode": "frost"} in bodies


async def test_unreachable_server_retries(hass: HomeAssistant, aioclient_mock, house):
    aioclient_mock.get(f"{URL}/api/v1/house", exc=TimeoutError)
    entry = MockConfigEntry(domain=DOMAIN, unique_id=house["id"], data={CONF_URL: URL})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
