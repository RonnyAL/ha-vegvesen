"""Short-lived source catalogues and bundled, coordinate-checked UI geography."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RoadCamera, VegvesenApiClient, WeatherStation
from .const import DOMAIN, LOGGER, WEATHER_UPDATE_INTERVAL
from .route_api import RouteApiClient

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from homeassistant.core import HomeAssistant

CATALOGUE_TTL = 15 * 60


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """Administrative names apply only to the captured source coordinates."""

    latitude: float
    longitude: float
    county: str
    municipality: str


def parse_source_geography(payload: Any) -> dict[str, SourceLocation]:
    """Reject the entire supplemental index if its format is malformed."""
    if (
        not isinstance(payload, dict)
        or payload.get("version") != 1
        or not isinstance(payload.get("sources"), dict)
    ):
        raise ValueError("Invalid source geography index")
    locations = {}
    for key, record in payload["sources"].items():
        if (
            not isinstance(key, str)
            or not key.startswith(("weather_station:", "camera:"))
            or not isinstance(record, dict)
            or any(
                type(record.get(field)) not in (int, float)
                for field in ("latitude", "longitude")
            )
            or any(
                not isinstance(record.get(field), str) or not record[field]
                for field in ("county", "municipality")
            )
        ):
            raise ValueError("Invalid source geography record")
        locations[key] = SourceLocation(
            record["latitude"],
            record["longitude"],
            record["county"],
            record["municipality"],
        )
    return locations


def _read_source_geography() -> dict[str, SourceLocation]:
    """Read and parse package metadata in HA's executor, never on its event loop."""
    return parse_source_geography(
        json.loads(Path(__file__).with_name("source_geography.json").read_text())
    )


class CatalogueCache[T: WeatherStation | RoadCamera]:
    """Coalesce simultaneous flows without caching failures or partial pages."""

    def __init__(
        self, fetch: Callable[[], Awaitable[dict[str, T]]], ttl: float = CATALOGUE_TTL
    ) -> None:
        """Keep one family independent from the other."""
        self._fetch = fetch
        self._lock = asyncio.Lock()
        self._snapshot: dict[str, T] = {}
        self._expires = 0.0
        self._ttl = ttl

    @property
    def fresh(self) -> bool:
        """Allow HA's sub-second poll jitter without skipping a full interval."""
        return monotonic() < self._expires - 1

    async def async_get(self, *, refresh_empty: bool = False) -> dict[str, T]:
        """Return a copy; allow configuration to retry an empty catalogue."""
        async with self._lock:
            if not self.fresh or (refresh_empty and not self._snapshot):
                snapshot = await self._fetch()
                self._snapshot = snapshot
                self._expires = monotonic() + self._ttl
            return dict(self._snapshot)


class DiscoveryCache:
    """Shared clients, cooldowns and discovery; no timers or entity state."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Use the shared session; the cache never closes it."""
        self._hass = hass
        session = async_get_clientsession(hass)
        self.client = VegvesenApiClient(session)
        self.route_client = RouteApiClient(session, self.client)
        self.weather = CatalogueCache(
            self.client.async_get_weather, ttl=WEATHER_UPDATE_INTERVAL.total_seconds()
        )
        self.cameras = CatalogueCache(self.client.async_get_cameras)
        self._geography: dict[str, SourceLocation] | None = None
        self._geography_lock = asyncio.Lock()

    async def async_geography(self) -> dict[str, SourceLocation]:
        """Unavailable supplemental geography cannot hide any real sources."""
        async with self._geography_lock:
            if self._geography is None:
                try:
                    self._geography = await self._hass.async_add_executor_job(
                        _read_source_geography
                    )
                except (OSError, ValueError):
                    LOGGER.warning(
                        "Cannot read source geography; "
                        "sources will use unknown administrative areas"
                    )
                    self._geography = {}
            return self._geography


def async_get_discovery(hass: HomeAssistant) -> DiscoveryCache:
    """Share catalogues between flows within this HA instance only."""
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = DiscoveryCache(hass)
    return hass.data[DOMAIN]
