"""Polls the Radiate server for live state."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RadiateAuthError, RadiateClient, RadiateConnectionError
from .const import DOMAIN, SCAN_INTERVAL_S

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
            state = await self.client.state()
        except RadiateAuthError as err:
            raise ConfigEntryAuthFailed from err
        except RadiateConnectionError as err:
            raise UpdateFailed(str(err)) from err
        state["rooms_by_id"] = {r["id"]: r for r in state["rooms"]}
        return state
