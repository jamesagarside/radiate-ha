"""Config flow: connect to a Radiate server by URL, or via the Home Assistant App."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .api import RadiateAuthError, RadiateClient, RadiateConnectionError
from .const import CONF_TOKEN, CONF_URL, DEFAULT_URL, DOMAIN
from .options_flow import RadiateOptionsFlow


class RadiateConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> RadiateOptionsFlow:
        return RadiateOptionsFlow()

    async def _validate(self, url: str, token: str) -> dict:
        client = RadiateClient(async_get_clientsession(self.hass), url, token)
        return await client.house()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            token = user_input.get(CONF_TOKEN, "")
            try:
                house = await self._validate(url, token)
            except RadiateAuthError:
                errors["base"] = "invalid_auth"
            except RadiateConnectionError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(house["id"])
                self._abort_if_unique_id_configured(updates={CONF_URL: url, CONF_TOKEN: token})
                return self.async_create_entry(
                    title="Radiate", data={CONF_URL: url, CONF_TOKEN: token}
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_URL, default=(user_input or {}).get(CONF_URL, DEFAULT_URL)): str,
                vol.Optional(CONF_TOKEN, default=""): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_hassio(self, discovery_info: HassioServiceInfo) -> ConfigFlowResult:
        """Discovered from the Radiate Home Assistant App via the Supervisor."""
        cfg = discovery_info.config
        url = f"http://{cfg['host']}:{cfg['port']}"
        token = cfg.get("token", "")
        try:
            house = await self._validate(url, token)
        except RadiateConnectionError, RadiateAuthError:
            return self.async_abort(reason="cannot_connect")
        await self.async_set_unique_id(house["id"])
        self._abort_if_unique_id_configured(updates={CONF_URL: url, CONF_TOKEN: token})
        self._discovered = {CONF_URL: url, CONF_TOKEN: token}
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Radiate", data=self._discovered)
        return self.async_show_form(step_id="hassio_confirm")
