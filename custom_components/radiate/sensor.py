"""Room and boiler sensors, including learned model parameters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RadiateConfigEntry
from .entity import RadiateEntity


@dataclass(frozen=True, kw_only=True)
class RadiateSensorDescription(SensorEntityDescription):
    value: Callable[[dict], Any]


ROOM_SENSORS = (
    RadiateSensorDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value=lambda r: r.get("temperature"),
    ),
    RadiateSensorDescription(
        key="opening_limit",
        translation_key="opening_limit",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda r: r.get("opening"),
    ),
    RadiateSensorDescription(
        key="heating_gain",
        translation_key="heating_gain",
        native_unit_of_measurement="K/h",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=2,
        value=lambda r: (r.get("model") or {}).get("a"),
    ),
    RadiateSensorDescription(
        key="loss_rate",
        translation_key="loss_rate",
        native_unit_of_measurement="1/h",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=3,
        value=lambda r: (r.get("model") or {}).get("b"),
    ),
    RadiateSensorDescription(
        key="arrival_lag",
        translation_key="arrival_lag",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda r: (r.get("model") or {}).get("arrival_lag_min"),
    ),
    RadiateSensorDescription(
        key="confidence",
        translation_key="confidence",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda r: round(r["model"]["confidence"] * 100) if r.get("model") else None,
    ),
)

HOUSE_SENSORS = (
    RadiateSensorDescription(
        key="boiler_state",
        translation_key="boiler_state",
        device_class=SensorDeviceClass.ENUM,
        options=["idle", "lead", "firing", "rest"],
        value=lambda s: s["boiler"]["state"],
    ),
    RadiateSensorDescription(
        key="starts_last_hour",
        translation_key="starts_last_hour",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda s: s["boiler"]["starts_last_hour"],
    ),
    RadiateSensorDescription(
        key="predicted_burn",
        translation_key="predicted_burn",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value=lambda s: s["boiler"]["predicted_burn_min"],
    ),
    RadiateSensorDescription(
        key="outdoor_temperature",
        translation_key="outdoor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value=lambda s: s.get("outdoor"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RadiateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    entities: list[SensorEntity] = [RadiateHouseSensor(coordinator, d) for d in HOUSE_SENSORS]
    for room in coordinator.house["rooms"]:
        for d in ROOM_SENSORS:
            if d.key != "temperature" and not room["controllable"]:
                continue
            entities.append(RadiateRoomSensor(coordinator, d, room))
    async_add_entities(entities)


class RadiateRoomSensor(RadiateEntity, SensorEntity):
    entity_description: RadiateSensorDescription

    def __init__(self, coordinator, description: RadiateSensorDescription, room: dict) -> None:
        super().__init__(coordinator, description.key, room)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.room)


class RadiateHouseSensor(RadiateEntity, SensorEntity):
    entity_description: RadiateSensorDescription

    def __init__(self, coordinator, description: RadiateSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.coordinator.data)
