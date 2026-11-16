"""Boiler firing and per-room fire detection."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RadiateConfigEntry
from .entity import RadiateEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RadiateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    entities: list[BinarySensorEntity] = [BoilerFiring(coordinator)]
    entities += [
        RoomFire(coordinator, room)
        for room in coordinator.house["rooms"]
        if room.get("heat_source") == "episodic"
    ]
    async_add_entities(entities)


class BoilerFiring(RadiateEntity, BinarySensorEntity):
    _attr_translation_key = "boiler_firing"
    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "boiler_firing")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data["boiler"]["state"] == "firing"


class RoomFire(RadiateEntity, BinarySensorEntity):
    _attr_translation_key = "fire"
    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, coordinator, room: dict) -> None:
        super().__init__(coordinator, "fire", room)

    @property
    def is_on(self) -> bool:
        return bool(self.room.get("fire"))
