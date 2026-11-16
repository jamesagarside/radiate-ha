"""One climate entity per controllable room."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
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
        RadiateClimate(coordinator, room)
        for room in coordinator.house["rooms"]
        if room["controllable"]
    )


class RadiateClimate(RadiateEntity, ClimateEntity):
    _attr_name = None
    _attr_translation_key = "room"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.AUTO]
    _attr_hvac_mode = HVACMode.AUTO
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_min_temp = 5.0
    _attr_max_temp = 28.0
    _attr_target_temperature_step = 0.5

    def __init__(self, coordinator, room: dict) -> None:
        super().__init__(coordinator, "climate", room)

    @property
    def current_temperature(self) -> float | None:
        return self.room.get("temperature")

    @property
    def target_temperature(self) -> float | None:
        return self.room.get("target")

    @property
    def hvac_action(self) -> HVACAction:
        r = self.room
        if r.get("calling") or r.get("preheating") or r.get("topup"):
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        r = self.room
        return {
            "opening_limit": r.get("opening"),
            "preheating": r.get("preheating"),
            "fire": r.get("fire"),
            "learning": r.get("learning") or "active",
            "reason": r.get("reason"),
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        return None  # Radiate rooms are always schedule-driven; house mode is a service

    async def async_set_temperature(self, **kwargs: Any) -> None:
        try:
            await self.coordinator.client.set_setpoint(self._room_id, kwargs[ATTR_TEMPERATURE])
        except RadiateError as err:
            raise HomeAssistantError(f"Radiate: {err}") from err
        await self.coordinator.async_request_refresh()
