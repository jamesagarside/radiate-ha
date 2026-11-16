"""Home Assistant integration tests. Run with the HA test harness:

.venv-ha/bin/pytest tests/ha
"""

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
URL = "http://radiate.test:8099"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def house() -> dict:
    return json.loads((FIXTURES / "house.json").read_text())


@pytest.fixture
def state() -> dict:
    return json.loads((FIXTURES / "state.json").read_text())


@pytest.fixture
def radiate_api(aioclient_mock, house, state):
    aioclient_mock.get(f"{URL}/api/v1/house", json=house)
    aioclient_mock.get(f"{URL}/api/v1/state", json=state)
    for path in ("rooms/bedroom_1/setpoint", "store/boost", "mode"):
        aioclient_mock.post(f"{URL}/api/v1/{path}", json={"ok": True})
    return aioclient_mock
