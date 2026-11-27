"""One climate entity per controllable room, plus the override services."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RadiateConfigEntry
from .api import RadiateError
from .const import DOMAIN
from .entity import RadiateEntity

SETPOINT_MIN_C = 5.0
SETPOINT_MAX_C = 28.0
OVERRIDE_UNTIL = ("next_change", "duration", "cleared")
OVERRIDE_MAX_MIN = 7 * 24 * 60
ATTR_UNTIL = "until"
ATTR_DURATION_MIN = "duration_min"


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
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "set_override",
        {
            vol.Required(ATTR_TEMPERATURE): vol.All(
                vol.Coerce(float), vol.Range(min=SETPOINT_MIN_C, max=SETPOINT_MAX_C)
            ),
            vol.Optional(ATTR_UNTIL): vol.In(OVERRIDE_UNTIL),
            vol.Optional(ATTR_DURATION_MIN): vol.All(
                cv.positive_int, vol.Range(min=1, max=OVERRIDE_MAX_MIN)
            ),
        },
        "async_set_override",
    )
    platform.async_register_entity_service("clear_override", None, "async_clear_override")


class RadiateClimate(RadiateEntity, ClimateEntity):
    _attr_name = None
    _attr_translation_key = "room"
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.AUTO]
    _attr_hvac_mode = HVACMode.AUTO
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_min_temp = SETPOINT_MIN_C
    _attr_max_temp = SETPOINT_MAX_C
    _attr_target_temperature_step = 0.5

    def __init__(self, coordinator, room: dict) -> None:
        super().__init__(coordinator, "climate", room)

    @property
    def native_current_temperature(self) -> float | None:
        return self.room.get("temperature")

    @property
    def native_target_temperature(self) -> float | None:
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
        override = r.get("override") or {}
        return {
            "opening_limit": r.get("opening"),
            "preheating": r.get("preheating"),
            "fire": r.get("fire"),
            "learning": r.get("learning") or "active",
            "reason": r.get("reason"),
            "override_setpoint": override.get("setpoint"),
            "override_until": override.get("until"),
            "override_expires_in_min": override.get("expires_in_min"),
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        return None  # Radiate rooms are always schedule-driven; house mode is a service

    async def _post_setpoint(self, setpoint: float | None, **options: Any) -> None:
        try:
            await self.coordinator.client.set_setpoint(self._room_id, setpoint, **options)
        except RadiateError as err:
            raise HomeAssistantError(f"Radiate: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Override until the room's next scheduled change (the server's default)."""
        await self._post_setpoint(kwargs[ATTR_TEMPERATURE])

    async def async_set_override(
        self, temperature: float, until: str | None = None, duration_min: int | None = None
    ) -> None:
        if until == "duration" and duration_min is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="duration_needed"
            )
        if duration_min is not None and until not in (None, "duration"):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="duration_conflict"
            )
        await self._post_setpoint(temperature, until=until, duration_min=duration_min)

    async def async_clear_override(self) -> None:
        await self._post_setpoint(None)
