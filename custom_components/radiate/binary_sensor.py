"""Boiler firing, the hot-water store, detected fire and stuck valves."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RadiateConfigEntry
from .entity import RadiateEntity
from .presence import away_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RadiateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    entities: list[BinarySensorEntity] = [BoilerFiring(coordinator)]
    store = coordinator.data.get("store")
    entities += [
        cls(coordinator)
        for cls in (Store, StoreBoost)
        if isinstance(store, dict) and cls.FIELD in store
    ]
    entities += [
        RoomFire(coordinator, room)
        for room in coordinator.house["rooms"]
        if room.get("heat_source") == "episodic"
    ]
    # Servers before the stuck-valve check do not report `valve`.
    first = coordinator.data["rooms_by_id"]
    entities += [
        RoomValveUntrusted(coordinator, room)
        for room in coordinator.house["rooms"]
        if room["controllable"] and "valve" in first.get(room["id"], {})
    ]
    async_add_entities(entities)
    async_add_entities(away_entities(coordinator))


class BoilerFiring(RadiateEntity, BinarySensorEntity):
    _attr_translation_key = "boiler_firing"
    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "boiler_firing")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data["boiler"]["state"] == "firing"


class _StoreField(RadiateEntity, BinarySensorEntity):
    """One flag from the server's `store` object, with no device class.

    `heat` would label the states Hot and Normal, and `running` would say the store is
    heating. The relay only enables the store; the boiler's own thermostat decides when it
    heats.
    """

    FIELD: str

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, self._attr_translation_key)

    @property
    def available(self) -> bool:
        store = self.coordinator.data.get("store")
        return super().available and isinstance(store, dict) and self.FIELD in store

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data["store"][self.FIELD])


class Store(_StoreField):
    """On while the store relay is on: in a store window or during a store boost."""

    FIELD = "relay"
    _attr_translation_key = "store"


class StoreBoost(_StoreField):
    """On while a store boost runs."""

    FIELD = "boost"
    _attr_translation_key = "store_boost"


class RoomFire(RadiateEntity, BinarySensorEntity):
    """Fire as Radiate sees it: detected from the room warming, or set by the switch."""

    _attr_translation_key = "fire"
    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, coordinator, room: dict) -> None:
        super().__init__(coordinator, "fire", room)

    @property
    def is_on(self) -> bool:
        return bool(self.room.get("fire"))


class RoomValveUntrusted(RadiateEntity, BinarySensorEntity):
    """On when the room stayed cold through burns that warmed other rooms."""

    _attr_translation_key = "valve_untrusted"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, room: dict) -> None:
        super().__init__(coordinator, "valve_untrusted", room)

    @property
    def available(self) -> bool:
        return super().available and isinstance(self.room.get("valve"), dict)

    @property
    def is_on(self) -> bool:
        return bool(self.room["valve"].get("untrusted"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"misses": self.room["valve"].get("misses")}
