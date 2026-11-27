"""Fetching the state: one retry before the entities go unavailable."""

import aiohttp
import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant.test_util.aiohttp import AiohttpClientMockResponse

from custom_components.radiate import coordinator as coordinator_module

from .conftest import URL, setup_integration

STATE_URL = f"{URL}/api/v1/state"
CLIMATE = "climate.bedroom_1"


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(coordinator_module, "FETCH_RETRY_DELAY_S", 0)


def fail_next_fetches(aioclient_mock, state: dict, failures: int) -> list[int]:
    """Serve the state, but fail the next `failures` fetches as a lost DNS reply would.

    Returns a one-item list counting the fetches made from now on.
    """
    fetches = [0]

    async def respond(method, url, data):
        fetches[0] += 1
        if fetches[0] <= failures:
            raise aiohttp.ClientConnectionError("Timeout while contacting DNS servers")
        return AiohttpClientMockResponse(method, url, json=state)

    aioclient_mock.clear_requests()
    aioclient_mock.get(STATE_URL, side_effect=respond)
    return fetches


async def refresh(hass: HomeAssistant, entry) -> None:
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()


async def test_single_failed_fetch_is_retried(hass: HomeAssistant, radiate_api, house, state):
    entry = await setup_integration(hass, house)
    fetches = fail_next_fetches(radiate_api, state, failures=1)

    await refresh(hass, entry)

    assert fetches[0] == 2
    assert entry.runtime_data.coordinator.last_update_success
    assert hass.states.get(CLIMATE).state != STATE_UNAVAILABLE


async def test_second_failure_makes_entities_unavailable(
    hass: HomeAssistant, radiate_api, house, state
):
    entry = await setup_integration(hass, house)
    fetches = fail_next_fetches(radiate_api, state, failures=2)

    await refresh(hass, entry)

    assert fetches[0] == 2  # tried once more, not again and again
    assert not entry.runtime_data.coordinator.last_update_success
    assert hass.states.get(CLIMATE).state == STATE_UNAVAILABLE

    await refresh(hass, entry)
    assert hass.states.get(CLIMATE).state != STATE_UNAVAILABLE
