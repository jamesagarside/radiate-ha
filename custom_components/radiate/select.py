"""House-wide selects: the heating mode (auto, frost, off) and the demand mode (eco, comfort)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RadiateConfigEntry
from .api import RadiateError
from .entity import RadiateEntity

MODES = ["auto", "frost", "off"]
DEMAND_MODES = ["eco", "comfort"]


def _settings(state: dict) -> dict:
    settings = state.get("settings")
    return settings if isinstance(settings, dict) else {}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RadiateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    entities: list[SelectEntity] = []
    if "mode" in coordinator.data:
        entities.append(HeatingMode(coordinator))
    # Servers before runtime settings cannot change the demand mode.
    if "demand_mode" in _settings(coordinator.data):
        entities.append(DemandModeSelect(coordinator))
    async_add_entities(entities)


class HeatingMode(RadiateEntity, SelectEntity):
    """Shows `mode` from the server and posts `mode`, as the `radiate.set_mode` service does."""

    _attr_translation_key = "mode"
    _attr_options = MODES

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "mode")

    @property
    def available(self) -> bool:
        return super().available and "mode" in self.coordinator.data

    @property
    def current_option(self) -> str | None:
        mode = self.coordinator.data["mode"]
        return mode if mode in MODES else None

    async def async_select_option(self, option: str) -> None:
        try:
            await self.coordinator.client.set_mode(option)
        except RadiateError as err:
            raise HomeAssistantError(f"Radiate: {err}") from err
        await self.coordinator.async_request_refresh()


class DemandModeSelect(RadiateEntity, SelectEntity):
    """Shows `settings.demand_mode` and posts `settings`.

    Choosing the configured default posts null, so the server follows
    `boiler.demand_mode` in its configuration file again, as the web UI does.
    """

    _attr_translation_key = "demand_mode"
    _attr_options = DEMAND_MODES

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "demand_mode")

    @property
    def available(self) -> bool:
        return super().available and (
            _settings(self.coordinator.data).get("demand_mode") in DEMAND_MODES
        )

    @property
    def current_option(self) -> str | None:
        return _settings(self.coordinator.data).get("demand_mode")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"default_mode": _settings(self.coordinator.data).get("demand_mode_default")}

    async def async_select_option(self, option: str) -> None:
        default = _settings(self.coordinator.data).get("demand_mode_default")
        try:
            await self.coordinator.client.set_demand_mode(None if option == default else option)
        except RadiateError as err:
            raise HomeAssistantError(f"Radiate: {err}") from err
        await self.coordinator.async_request_refresh()
