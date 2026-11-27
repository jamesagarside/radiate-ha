"""Polls the Radiate server for live state."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RadiateAuthError, RadiateClient, RadiateConnectionError
from .const import DOMAIN, FETCH_RETRY_DELAY_S, SCAN_INTERVAL_S

_LOGGER = logging.getLogger(__name__)


class RadiateCoordinator(DataUpdateCoordinator[dict]):
    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: RadiateClient, house: dict
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_S),
        )
        self.client = client
        self.house = house
        # The house device's registry id, set at setup, so room devices can link to it
        self.house_device_id: str | None = None

    async def _async_update_data(self) -> dict:
        try:
            state = await self._fetch_state()
        except RadiateAuthError as err:
            raise ConfigEntryAuthFailed from err
        except RadiateConnectionError as err:
            raise UpdateFailed(str(err)) from err
        state["rooms_by_id"] = {r["id"]: r for r in state["rooms"]}
        return state

    async def _fetch_state(self) -> dict:
        """Fetch the state, trying once more if the server can't be reached."""
        try:
            return await self.client.state()
        except RadiateConnectionError as err:
            _LOGGER.debug("Fetching state failed, trying again: %s", err)
        await asyncio.sleep(FETCH_RETRY_DELAY_S)
        return await self.client.state()
