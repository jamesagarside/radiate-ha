"""Shared entity base: one device for the house, one per room."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RadiateCoordinator


def house_device(coordinator: RadiateCoordinator) -> DeviceInfo:
    house = coordinator.house
    return DeviceInfo(
        identifiers={(DOMAIN, house["id"])},
        name="Radiate",
        manufacturer="Radiate",
        model=f"Radiate ({house.get('driver', 'server')})",
        sw_version=house.get("version"),
    )


class RadiateEntity(CoordinatorEntity[RadiateCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: RadiateCoordinator, key: str, room: dict | None = None) -> None:
        super().__init__(coordinator)
        house_id = coordinator.house["id"]
        self._room_id = room["id"] if room else None
        self._attr_unique_id = f"{house_id}_{self._room_id or 'house'}_{key}"
        if room:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{house_id}_{room['id']}")},
                name=room["name"],
                manufacturer="Radiate",
                model="Room",
                via_device=(DOMAIN, house_id),
            )
        else:
            self._attr_device_info = house_device(coordinator)

    @property
    def room(self) -> dict:
        return self.coordinator.data["rooms_by_id"].get(self._room_id, {})
