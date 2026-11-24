"""Outdoor temperature: report a Home Assistant entity's temperature to the server.

The entity is picked in the options flow (none by default): a `weather` entity, whose
`temperature` attribute is read, or a `sensor` with device class temperature, whose
state is read. Either is converted to °C. The integration posts it to
`POST /api/v1/outdoor` when it changes and every 15 minutes (the heartbeat), with
`measured_at` from the entity's `last_reported` (falling back to `last_updated`), so
the server can tell a reading that stopped updating from a fresh one. `unknown`,
`unavailable` and non-numeric values are not sent.

The server decides whether to use it (`house.outdoor_source`), how old is too old and
what to assume without it; nothing here makes that decision.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta

from homeassistant.const import (
    ATTR_TEMPERATURE,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State
from homeassistant.core import callback as ha_callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util.unit_conversion import TemperatureConverter

from .api import RadiateError
from .const import CONF_OUTDOOR, PRESENCE_HEARTBEAT_MIN

_LOGGER = logging.getLogger(__name__)

WEATHER_DOMAIN = "weather"
SENSOR_DOMAIN = "sensor"
# The weather entity's unit for `temperature`; read as a string so the weather
# integration need not be loaded.
ATTR_WEATHER_TEMPERATURE_UNIT = "temperature_unit"
UNITS = {u.value for u in UnitOfTemperature}


def outdoor_temperature(state: State | None) -> float | None:
    """The entity's temperature in °C, or None when it has no usable one."""
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    if state.domain == WEATHER_DOMAIN:
        raw = state.attributes.get(ATTR_TEMPERATURE)
        unit = state.attributes.get(ATTR_WEATHER_TEMPERATURE_UNIT)
    else:
        raw = state.state
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    if unit in UNITS and unit != UnitOfTemperature.CELSIUS:
        value = TemperatureConverter.convert(value, unit, UnitOfTemperature.CELSIUS)
    return round(value, 2)


def measured_at(state: State) -> datetime:
    """When the entity last reported, whether or not its value changed."""
    return getattr(state, "last_reported", None) or state.last_updated


def _posted_by_an_entity(reading: dict | None) -> bool:
    """A reading on the server that an entity like ours posted (its source is an entity ID)."""
    source = (reading or {}).get("source") or ""
    return source.startswith((f"{WEATHER_DOMAIN}.", f"{SENSOR_DOMAIN}."))


async def async_setup_outdoor(hass: HomeAssistant, entry) -> None:
    """Report the chosen outdoor entity now, when it changes and on the heartbeat."""
    data = entry.runtime_data
    entity_id: str | None = entry.options.get(CONF_OUTDOOR)

    if not entity_id:
        # The option was cleared: forget a reading an entity posted, so it goes stale
        # on the server at once rather than standing until its age runs out.
        reading = (data.coordinator.data.get("outdoor_reading") or {}).get("home_assistant")
        if _posted_by_an_entity(reading):
            try:
                await data.client.report_outdoor(None)
            except RadiateError as err:
                _LOGGER.debug("Radiate: could not forget the outdoor temperature: %s", err)
        return

    warned = False

    async def report(state: State | None) -> None:
        nonlocal warned
        value = outdoor_temperature(state)
        if value is None:
            return
        try:
            await data.client.report_outdoor(value, measured_at(state).isoformat(), entity_id)
        except RadiateError as err:
            # A server from before outdoor readings does not have the route.
            if not warned:
                _LOGGER.warning("Radiate: could not report the outdoor temperature: %s", err)
                warned = True
            return
        warned = False

    await report(hass.states.get(entity_id))

    @ha_callback
    def changed(event: Event[EventStateChangedData]) -> None:
        new = outdoor_temperature(event.data["new_state"])
        if new is None or new == outdoor_temperature(event.data["old_state"]):
            return  # unknown, or another attribute of a weather entity changed
        entry.async_create_task(hass, report(event.data["new_state"]))

    entry.async_on_unload(async_track_state_change_event(hass, [entity_id], changed))

    async def heartbeat(_now: datetime) -> None:
        await report(hass.states.get(entity_id))

    entry.async_on_unload(
        async_track_time_interval(hass, heartbeat, timedelta(minutes=PRESENCE_HEARTBEAT_MIN))
    )
