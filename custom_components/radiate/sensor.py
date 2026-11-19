"""Room and boiler sensors, learned model parameters, daily accounting and alerts."""

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
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RadiateConfigEntry
from .entity import RadiateEntity


@dataclass(frozen=True, kw_only=True)
class RadiateSensorDescription(SensorEntityDescription):
    value: Callable[[dict], Any]
    # Whether the server reports this value. Checked against the first state to decide
    # whether to create the entity (older servers lack newer keys), then on every update
    # for availability.
    exists: Callable[[dict], bool] = lambda _: True
    attrs: Callable[[dict], dict[str, Any]] | None = None


def _accounting(state: dict, day: str) -> dict:
    return (state.get("accounting") or {}).get(day) or {}


def _has_today(key: str) -> Callable[[dict], bool]:
    return lambda s: key in _accounting(s, "today")


def _has_today_value(key: str) -> Callable[[dict], bool]:
    """Litres and kWh are null until a nozzle rating is configured."""
    return lambda s: _accounting(s, "today").get(key) is not None


def _alerts(state: dict) -> list[dict[str, Any]]:
    details = state.get("alert_details")
    if isinstance(details, list):
        return [
            {"code": a.get("code"), "message": a.get("message"), "room_id": a.get("room_id")}
            for a in details
        ]
    # Servers before alert_details report messages only.
    return [{"code": None, "message": m, "room_id": None} for m in state.get("alerts") or []]


def _short_cycle_attrs(state: dict) -> dict[str, Any]:
    boiler = state["boiler"]
    sc = boiler.get("short_cycle") or {}
    min_off_s = boiler.get("min_off_s")
    return {
        "ends_in_h": sc.get("ends_in_h"),
        "min_off_min": round(min_off_s / 60) if min_off_s is not None else None,
    }


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
        key="learning",
        translation_key="learning",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda r: r.get("learning") or "active",
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
    RadiateSensorDescription(
        key="short_cycle_extra_off",
        translation_key="short_cycle_extra_off",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        exists=lambda s: "short_cycle" in s["boiler"],
        value=lambda s: (s["boiler"]["short_cycle"] or {}).get("extra_off_min", 0),
        attrs=_short_cycle_attrs,
    ),
    # Daily totals restart from zero at local midnight, which TOTAL_INCREASING allows.
    RadiateSensorDescription(
        key="burner_hours_today",
        translation_key="burner_hours_today",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        exists=_has_today("burner_hours"),
        value=lambda s: _accounting(s, "today").get("burner_hours"),
        attrs=lambda s: {"basis": _accounting(s, "today").get("basis")},
    ),
    RadiateSensorDescription(
        key="relay_starts_today",
        translation_key="relay_starts_today",
        state_class=SensorStateClass.TOTAL_INCREASING,
        exists=_has_today("starts"),
        value=lambda s: _accounting(s, "today").get("starts"),
        attrs=lambda s: {
            "max_starts_in_hour": _accounting(s, "today").get("max_starts_in_hour"),
        },
    ),
    RadiateSensorDescription(
        key="oil_today",
        translation_key="oil_today",
        device_class=SensorDeviceClass.VOLUME,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        exists=_has_today_value("litres"),
        value=lambda s: _accounting(s, "today").get("litres"),
        attrs=lambda s: {"basis": _accounting(s, "today").get("basis")},
    ),
    RadiateSensorDescription(
        key="heat_today",
        translation_key="heat_today",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        exists=_has_today_value("kwh"),
        value=lambda s: _accounting(s, "today").get("kwh"),
        attrs=lambda s: {"basis": _accounting(s, "today").get("basis")},
    ),
    RadiateSensorDescription(
        key="balance_score_yesterday",
        translation_key="balance_score_yesterday",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        exists=lambda s: "yesterday" in (s.get("accounting") or {}),
        value=lambda s: (_accounting(s, "yesterday").get("balance") or {}).get("score"),
        attrs=lambda s: {
            k: (_accounting(s, "yesterday").get("balance") or {}).get(k)
            for k in ("arrival_spread_min", "starts_measured")
        },
    ),
    RadiateSensorDescription(
        key="alerts",
        translation_key="alerts",
        state_class=SensorStateClass.MEASUREMENT,
        exists=lambda s: "alerts" in s,
        value=lambda s: len(_alerts(s)),
        attrs=lambda s: {"alerts": _alerts(s)},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RadiateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    entities: list[SensorEntity] = [
        RadiateHouseSensor(coordinator, d) for d in HOUSE_SENSORS if d.exists(coordinator.data)
    ]
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
    def available(self) -> bool:
        return super().available and self.entity_description.exists(self.coordinator.data)

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs = self.entity_description.attrs
        return attrs(self.coordinator.data) if attrs else None
