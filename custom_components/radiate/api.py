"""Client for the Radiate server API (docs/spec.md section 8.1).

The integration is a thin client: all control logic lives in the Radiate server,
which keeps heating running when Home Assistant restarts (ADR-0002).
"""

from __future__ import annotations

from typing import Any

import aiohttp


class RadiateError(Exception):
    """Base error."""


class RadiateConnectionError(RadiateError):
    """Server unreachable or returned an unexpected response."""


class RadiateAuthError(RadiateError):
    """Token rejected."""


class RadiateClient:
    def __init__(self, session: aiohttp.ClientSession, url: str, token: str = "") -> None:
        self._session = session
        self._url = url.rstrip("/")
        self._token = token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    async def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        try:
            async with self._session.request(
                method,
                f"{self._url}/api/v1/{path}",
                json=body,
                headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 401:
                    raise RadiateAuthError
                if resp.status >= 400:
                    detail = (await resp.text())[:200]
                    raise RadiateConnectionError(f"{method} {path}: HTTP {resp.status} {detail}")
                return await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise RadiateConnectionError(str(err)) from err

    async def house(self) -> dict:
        return await self._request("GET", "house")

    async def state(self) -> dict:
        return await self._request("GET", "state")

    async def set_setpoint(
        self,
        room_id: str,
        setpoint: float | None,
        until: str | None = None,
        duration_min: int | None = None,
    ) -> None:
        """Override a room's setpoint; `None` clears the override.

        Without `until` or `duration_min` the server holds it until the next schedule change.
        """
        body: dict[str, Any] = {"setpoint": setpoint}
        if until is not None:
            body["until"] = until
        if duration_min is not None:
            body["duration_min"] = duration_min
        await self._request("POST", f"rooms/{room_id}/setpoint", body)

    async def set_fire(self, room_id: str, lit: bool) -> None:
        await self._request("POST", f"rooms/{room_id}/fire", {"lit": lit})

    async def boost_store(self, minutes: int) -> None:
        await self._request("POST", "store/boost", {"minutes": minutes})

    async def set_mode(self, mode: str) -> None:
        await self._request("POST", "mode", {"mode": mode})

    async def set_demand_mode(self, mode: str | None) -> None:
        """`eco` or `comfort`; `None` follows `boiler.demand_mode` in the server's config."""
        await self._request("POST", "settings", {"demand_mode": mode})

    async def set_away(self, person_id: str, until: str | None) -> None:
        """Away until an ISO 8601 date and time; `None` clears it."""
        await self._request("POST", f"people/{person_id}/away", {"until": until})

    async def report_presence(
        self,
        person_id: str,
        state: str | None,
        since: str | None = None,
        evidence_at: str | None = None,
        source_type: str | None = None,
        battery: float | None = None,
    ) -> None:
        """Presence from a `person` entity: `home`, `not_home`, or `None` to forget it.

        `evidence_at`, `source_type` and `battery` are what its trackers say, for the
        server's fail warm rules; each is sent only when known.
        """
        body: dict[str, Any] = {"state": state}
        if since is not None:
            body["since"] = since
        for key, value in (
            ("evidence_at", evidence_at),
            ("source_type", source_type),
            ("battery", battery),
        ):
            if value is not None:
                body[key] = value
        await self._request("POST", f"people/{person_id}/presence", body)

    async def report_ha_persons(self, persons: list[dict[str, str]]) -> None:
        """The `person` entities Home Assistant has, `[{"entity_id", "name"}]`.

        The server offers them in its setup wizard, to link Radiate people to.
        """
        await self._request("POST", "ha/persons", {"persons": persons})
