"""Options: map each Radiate person to a Home Assistant `person` entity.

People come from the server's household (`GET /api/v1/house`). A mapped person's
presence is reported to the server as it changes; see `presence.py`.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlowResult, OptionsFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from .api import RadiateAuthError, RadiateClient, RadiateConnectionError
from .const import CONF_PEOPLE, CONF_TOKEN, CONF_URL


class RadiateOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._people: list[dict] = []

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            chosen = {p["id"]: user_input.get(p["id"]) for p in self._people}
            return self.async_create_entry(
                data={
                    **self.config_entry.options,
                    CONF_PEOPLE: {k: v for k, v in chosen.items() if v},
                }
            )

        entry = self.config_entry
        client = RadiateClient(
            async_get_clientsession(self.hass), entry.data[CONF_URL], entry.data.get(CONF_TOKEN, "")
        )
        try:
            house = await client.house()
        except (RadiateConnectionError, RadiateAuthError):
            return self.async_abort(reason="cannot_connect")
        self._people = house.get("people") or []
        if not self._people:
            return self.async_abort(reason="no_people")

        current = entry.options.get(CONF_PEOPLE) or {}
        selector = EntitySelector(EntitySelectorConfig(domain="person"))
        schema = vol.Schema(
            {
                vol.Optional(
                    p["id"], description={"suggested_value": current.get(p["id"])}
                ): selector
                for p in self._people
            }
        )
        names = ", ".join(f"{p['id']} ({p['name']})" for p in self._people)
        return self.async_show_form(
            step_id="init", data_schema=schema, description_placeholders={"people": names}
        )
