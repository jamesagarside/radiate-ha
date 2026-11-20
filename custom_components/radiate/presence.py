"""Away: presence from Home Assistant `person` entities, away entities and services.

The options flow maps each Radiate person to a `person` entity. This module reports
those entities' states to the server as they change: `home` is home, any other state
(`not_home` or a zone name) is not home, and `unknown` or `unavailable` are not
reported, so they never count as away. Every 15 minutes it reports each known state
again (a heartbeat), so the server can treat presence that stops arriving as unknown.
The server decides who counts as away (with its presence delay and stale limit) and what
that does to the heating; nothing here makes that decision.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import STATE_HOME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, ServiceCall, State
from homeassistant.core import callback as ha_callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .api import RadiateError
from .const import CONF_PEOPLE, DOMAIN, PRESENCE_HEARTBEAT_MIN
from .entity import RadiateEntity

_LOGGER = logging.getLogger(__name__)

SET_AWAY_SCHEMA = vol.Schema(
    {vol.Required("person"): cv.string, vol.Required("until"): cv.datetime}
)
CLEAR_AWAY_SCHEMA = vol.Schema({vol.Required("person"): cv.string})


def presence_of(state: State | None) -> str | None:
    """`home`, `not_home`, or None when Home Assistant does not know."""
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    return "home" if state.state == STATE_HOME else "not_home"


def people(entry) -> list[dict]:
    """The server's people, from `/house`. Empty for a server without a household."""
    return entry.runtime_data.coordinator.house.get("people") or []


def mapping(entry) -> dict[str, str]:
    """Radiate person id to `person` entity id, for people the server still has."""
    known = {p["id"] for p in people(entry)}
    chosen = entry.options.get(CONF_PEOPLE) or {}
    return {pid: eid for pid, eid in chosen.items() if pid in known and eid}


async def async_setup_presence(hass: HomeAssistant, entry) -> None:
    """Report mapped people's presence now and whenever their `person` entity changes."""
    data = entry.runtime_data
    chosen = mapping(entry)

    async def report(
        person_id: str, state: str | None, since: datetime | None, refresh: bool = True
    ) -> None:
        try:
            await data.client.report_presence(
                person_id, state, since.isoformat() if since else None
            )
        except RadiateError as err:
            _LOGGER.warning("Radiate: could not report presence for %s: %s", person_id, err)
            return
        if refresh:
            await data.coordinator.async_request_refresh()

    # Forget presence for people who are no longer mapped, so it cannot go stale.
    for person in (data.coordinator.data.get("away") or {}).get("people", []):
        if person["id"] not in chosen and person.get("presence"):
            await report(person["id"], None, None)
    for pid, entity_id in chosen.items():
        state = hass.states.get(entity_id)
        value = presence_of(state)
        if value is not None:
            await report(pid, value, state.last_changed)

    if not chosen:
        return
    by_entity: dict[str, list[str]] = {}
    for pid, entity_id in chosen.items():
        by_entity.setdefault(entity_id, []).append(pid)

    @ha_callback
    def changed(event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        value = presence_of(new)
        if value is None or value == presence_of(event.data["old_state"]):
            return  # unknown, or a move between zones: still not home since earlier
        for pid in by_entity.get(event.data["entity_id"], []):
            entry.async_create_task(hass, report(pid, value, new.last_changed))

    entry.async_on_unload(async_track_state_change_event(hass, list(by_entity), changed))

    async def heartbeat(_now: datetime) -> None:
        # The same state and change time again: nothing changes on the server except
        # that the presence is fresh. Unknown states are still not sent.
        for pid, entity_id in chosen.items():
            state = hass.states.get(entity_id)
            value = presence_of(state)
            if value is not None:
                await report(pid, value, state.last_changed, refresh=False)

    entry.async_on_unload(
        async_track_time_interval(hass, heartbeat, timedelta(minutes=PRESENCE_HEARTBEAT_MIN))
    )


def _resolve(entry, person: str) -> str | None:
    """A Radiate person id, given one or a mapped `person` entity id."""
    if any(p["id"] == person for p in people(entry)):
        return person
    for pid, entity_id in mapping(entry).items():
        if entity_id == person:
            return pid
    return None


def async_register_away_services(hass: HomeAssistant, entries) -> None:
    """`radiate.set_away` and `radiate.clear_away`. `entries()` lists loaded entries."""
    if hass.services.has_service(DOMAIN, "set_away"):
        return

    async def call(person: str, until: str | None) -> None:
        targets = [(e, pid) for e in entries() if (pid := _resolve(e, person)) is not None]
        if not targets:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_person",
                translation_placeholders={"person": person},
            )
        for entry, pid in targets:
            data = entry.runtime_data
            try:
                await data.client.set_away(pid, until)
            except RadiateError as err:
                raise HomeAssistantError(f"Radiate: {err}") from err
            await data.coordinator.async_request_refresh()

    async def set_away(service: ServiceCall) -> None:
        until: datetime = service.data["until"]
        if until.tzinfo is None:
            until = until.replace(tzinfo=dt_util.get_default_time_zone())
        await call(service.data["person"], until.isoformat())

    async def clear_away(service: ServiceCall) -> None:
        await call(service.data["person"], None)

    hass.services.async_register(DOMAIN, "set_away", set_away, schema=SET_AWAY_SCHEMA)
    hass.services.async_register(DOMAIN, "clear_away", clear_away, schema=CLEAR_AWAY_SCHEMA)


def away_entities(coordinator) -> list[BinarySensorEntity]:
    return [PersonAway(coordinator, person) for person in coordinator.house.get("people") or []]


class PersonAway(RadiateEntity, BinarySensorEntity):
    """On while Radiate counts the person as away, with the time they are due back."""

    _attr_translation_key = "away"

    def __init__(self, coordinator, person: dict) -> None:
        super().__init__(coordinator, f"away_{person['id']}")
        self._person_id = person["id"]
        self._attr_translation_placeholders = {"person": person["name"]}

    @property
    def person(self) -> dict | None:
        away = self.coordinator.data.get("away") or {}
        return next((p for p in away.get("people", []) if p["id"] == self._person_id), None)

    @property
    def available(self) -> bool:
        return super().available and self.person is not None

    @property
    def is_on(self) -> bool:
        return bool(self.person["away"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        p = self.person
        presence = p.get("presence") or {}
        return {
            "person_id": self._person_id,
            "reason": p.get("reason"),
            "away_until": p.get("until"),
            "presence": presence.get("state"),
            "presence_since": presence.get("since"),
            # Not reported for the server's stale limit: treated as unknown, not away.
            "presence_stale": presence.get("stale"),
        }
