from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.hassio import HassioServiceInfo
from pytest_homeassistant.common import MockConfigEntry

from custom_components.radiate.const import CONF_TOKEN, CONF_URL, DOMAIN

from .conftest import URL


async def test_user_flow_creates_entry(hass: HomeAssistant, radiate_api, house):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: URL + "/", CONF_TOKEN: "t0ken"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_URL: URL, CONF_TOKEN: "t0ken"}
    assert result["result"].unique_id == house["id"]


async def test_user_flow_cannot_connect(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(f"{URL}/api/v1/house", exc=TimeoutError)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_URL: URL})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_invalid_auth(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(f"{URL}/api/v1/house", status=401)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: URL, CONF_TOKEN: "x"}
    )
    assert result["errors"] == {"base": "invalid_auth"}


async def test_duplicate_house_aborts(hass: HomeAssistant, radiate_api, house):
    MockConfigEntry(domain=DOMAIN, unique_id=house["id"], data={CONF_URL: URL}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_URL: URL})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_hassio_discovery(hass: HomeAssistant, radiate_api):
    info = HassioServiceInfo(
        config={"host": "radiate.test", "port": 8099, "token": ""},
        name="Radiate",
        slug="radiate",
        uuid="1234",
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_HASSIO}, data=info
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "hassio_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_URL] == URL
