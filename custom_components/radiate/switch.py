"""Manual "fire lit" switch for rooms with an open fire or stove."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RadiateConfigEntry
from .api import RadiateError
from .entity import RadiateEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RadiateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        RoomFireSwitch(coordinator, room)
        for room in coordinator.house["rooms"]
        if room.get("heat_source") == "episodic"
    )


class RoomFireSwitch(RadiateEntity, SwitchEntity):
    """Posts `rooms/{id}/fire`.

    Shows the server's manual flag (`fire_switch`). Servers that do not report it get
    the last value set from here.
    """

    _attr_translation_key = "fire_switch"

    def __init__(self, coordinator, room: dict) -> None:
        super().__init__(coordinator, "fire_switch", room)
        self._last_set = False

    @property
    def assumed_state(self) -> bool:
        return "fire_switch" not in self.room

    @property
    def is_on(self) -> bool:
        if "fire_switch" in self.room:
            return bool(self.room["fire_switch"])
        return self._last_set

    async def _set(self, lit: bool) -> None:
        try:
            await self.coordinator.client.set_fire(self._room_id, lit)
        except RadiateError as err:
            raise HomeAssistantError(f"Radiate: {err}") from err
        self._last_set = lit
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
