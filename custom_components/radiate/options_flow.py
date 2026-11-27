"""Options: map each Radiate person to a Home Assistant `person` entity, and pick an
outdoor temperature entity.

People come from the server's household (`GET /api/v1/house`), which can also link
them in Radiate's setup wizard (`ha_person`). A mapping here wins over that link; a
person left empty here uses it. A mapped person's presence is reported to the server
as it changes; see `presence.py`.

The outdoor entity (none by default) is a `weather` entity or a temperature `sensor`.
Its temperature is reported to the server; see `outdoor.py`. The form shows it even
when the server has no people.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigFlowResult, OptionsFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    EntityFilterSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
)

from .api import RadiateAuthError, RadiateClient, RadiateConnectionError
from .const import CONF_OUTDOOR, CONF_PEOPLE, CONF_TOKEN, CONF_URL

OUTDOOR_SELECTOR = EntitySelector(
    EntitySelectorConfig(
        filter=[
            EntityFilterSelectorConfig(domain="weather"),
            EntityFilterSelectorConfig(domain="sensor", device_class=SensorDeviceClass.TEMPERATURE),
        ]
    )
)


def _describe(person: dict) -> str:
    """`early_riser (Early riser)`, with the link from Radiate's wizard when it has one."""
    link = person.get("ha_person")
    extra = f", linked in Radiate to {link}" if link else ""
    return f"{person['id']} ({person['name']}{extra})"


class RadiateOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._people: list[dict] = []

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            chosen = {p["id"]: user_input.get(p["id"]) for p in self._people}
            options = {
                **self.config_entry.options,
                CONF_PEOPLE: {k: v for k, v in chosen.items() if v},
            }
            options.pop(CONF_OUTDOOR, None)
            if user_input.get(CONF_OUTDOOR):
                options[CONF_OUTDOOR] = user_input[CONF_OUTDOOR]
            return self.async_create_entry(data=options)

        entry = self.config_entry
        client = RadiateClient(
            async_get_clientsession(self.hass), entry.data[CONF_URL], entry.data.get(CONF_TOKEN, "")
        )
        try:
            house = await client.house()
        except RadiateConnectionError, RadiateAuthError:
            return self.async_abort(reason="cannot_connect")
        self._people = house.get("people") or []

        current = entry.options.get(CONF_PEOPLE) or {}
        selector = EntitySelector(EntitySelectorConfig(domain="person"))
        fields: dict[Any, Any] = {
            vol.Optional(p["id"], description={"suggested_value": current.get(p["id"])}): selector
            for p in self._people
        }
        fields[
            vol.Optional(
                CONF_OUTDOOR, description={"suggested_value": entry.options.get(CONF_OUTDOOR)}
            )
        ] = OUTDOOR_SELECTOR
        names = ", ".join(_describe(p) for p in self._people) or "none yet"
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(fields),
            description_placeholders={"people": names},
        )
