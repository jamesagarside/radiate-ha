"""Radiate: whole-house hydronic balancing and boiler control.

This integration is a client of the Radiate server (standalone, Home Assistant App,
or cloud edge). It exposes rooms and the boiler as entities and adds services.
"""

from __future__ import annotations

from dataclasses import dataclass

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RadiateAuthError, RadiateClient, RadiateConnectionError, RadiateError
from .const import CONF_TOKEN, CONF_URL, DOMAIN
from .coordinator import RadiateCoordinator

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


@dataclass
class RadiateData:
    client: RadiateClient
    coordinator: RadiateCoordinator


type RadiateConfigEntry = ConfigEntry[RadiateData]


async def async_setup_entry(hass: HomeAssistant, entry: RadiateConfigEntry) -> bool:
    client = RadiateClient(
        async_get_clientsession(hass), entry.data[CONF_URL], entry.data.get(CONF_TOKEN, "")
    )
    try:
        house = await client.house()
    except RadiateAuthError as err:
        raise ConfigEntryAuthFailed from err
    except RadiateConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = RadiateCoordinator(hass, entry, client, house)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = RadiateData(client, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RadiateConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _clients(hass: HomeAssistant) -> list[RadiateData]:
    return [
        e.runtime_data
        for e in hass.config_entries.async_loaded_entries(DOMAIN)
        if isinstance(getattr(e, "runtime_data", None), RadiateData)
    ]


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, "boost_store"):
        return

    async def boost_store(call: ServiceCall) -> None:
        for data in _clients(hass):
            try:
                await data.client.boost_store(call.data["minutes"])
            except RadiateError as err:
                raise HomeAssistantError(f"Radiate: {err}") from err
            await data.coordinator.async_request_refresh()

    async def set_mode(call: ServiceCall) -> None:
        for data in _clients(hass):
            try:
                await data.client.set_mode(call.data["mode"])
            except RadiateError as err:
                raise HomeAssistantError(f"Radiate: {err}") from err
            await data.coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        "boost_store",
        boost_store,
        schema=vol.Schema(
            {vol.Optional("minutes", default=60): vol.All(cv.positive_int, vol.Range(max=180))}
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "set_mode",
        set_mode,
        schema=vol.Schema({vol.Required("mode"): vol.In(["auto", "off", "frost"])}),
    )
