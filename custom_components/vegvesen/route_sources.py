"""Shared, demand-driven map discovery without automatic entity ownership."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from dataclasses import dataclass
from datetime import timedelta
from time import monotonic
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RoadCamera, VegvesenApiError, VegvesenRateLimitError, WeatherStation
from .const import (
    IMAGE_REQUEST_TIMEOUT,
    LOGGER,
    REQUEST_TIMEOUT,
    WEATHER_UPDATE_INTERVAL,
)
from .discovery import CATALOGUE_TTL
from .route_geometry import make_corridor

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant

    from .api import VegvesenApiClient
    from .data import VegvesenConfigEntry
    from .discovery import CatalogueCache
    from .route_coordinator import RouteCoordinator

type Source = WeatherStation | RoadCamera


class SourceCoordinator(DataUpdateCoordinator[dict[str, Source]]):
    """Poll one complete catalogue only while map subscribers need it."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: VegvesenConfigEntry,
        cache: CatalogueCache,
        kind: str,
    ) -> None:
        """Share discovery with config flows and every route in the parent."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"Statens vegvesen map {kind}",
            update_interval=(
                WEATHER_UPDATE_INTERVAL
                if kind == "weather"
                else timedelta(seconds=CATALOGUE_TTL)
            ),
        )
        self.cache = cache

    async def _async_update_data(self) -> dict[str, Source]:
        """Never expose a partial or expired failed snapshot as healthy."""
        try:
            return await self.cache.async_get()
        except VegvesenRateLimitError as err:
            raise UpdateFailed(str(err), retry_after=err.retry_after) from err
        except VegvesenApiError as err:
            raise UpdateFailed(str(err)) from err


def matching_sources(
    geometry: dict[str, Any], distance: int, sources: dict[str, Source]
) -> list[Source]:
    """Match each point to the saved route, never to its forecast segments."""
    corridor = make_corridor(geometry, distance)
    return [
        source
        for source in sources.values()
        if source.longitude is not None
        and source.latitude is not None
        and math.isfinite(source.longitude)
        and math.isfinite(source.latitude)
        and -180 <= source.longitude <= 180  # noqa: PLR2004
        and -90 <= source.latitude <= 90  # noqa: PLR2004
        and corridor.intersects(
            {"type": "Point", "coordinates": [source.longitude, source.latitude]}
        )
    ]


def source_record(source: Source) -> dict[str, Any]:
    """Serialize only supported source fields; never expose image endpoints."""
    data = {
        "source_id": source.source_id,
        "name": source.name,
        "longitude": source.longitude,
        "latitude": source.latitude,
        "road_number": source.road_number,
    }
    if isinstance(source, WeatherStation):
        data.update(
            air_temperature=source.air_temperature,
            measurement_time=(
                source.measurement_time.isoformat() if source.measurement_time else None
            ),
        )
    else:
        data.update(orientation=source.orientation, availability=source.availability)
    return data


class SourceWatch:
    """Own the source listeners and cancellable filtering for one map subscription."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: VegvesenConfigEntry,
        msg: dict[str, Any],
        publish: Callable[[], None],
        send: Callable[[dict[str, Any]], None],
    ) -> None:
        """Leave identity and access checks to the surrounding route subscription."""
        self.hass, self.entry, self.msg = hass, entry, msg
        self.publish, self.send = publish, send
        self.route: RouteCoordinator | None = None
        self.removers: list[Callable[[], None]] = []
        self.task: asyncio.Task | None = None

    @callback
    def update(self, route: RouteCoordinator | None, error: str | None) -> None:
        """Rebind on reload; source failures do not depend on forecast health."""
        if self.task:
            self.task.cancel()
        if route is not self.route:
            self.close()
            self.route = route
            if route:
                for kind, coordinator in self.entry.runtime_data.sources.items():
                    if self.msg.get(f"show_{kind}"):
                        self.removers.append(
                            coordinator.async_add_listener(self.publish)
                        )
                        self.entry.async_create_background_task(
                            self.hass,
                            coordinator.async_request_refresh(),
                            f"vegvesen map {kind} refresh",
                            eager_start=False,
                        )
        if error or route is None:
            self.send({"error": error or "unavailable"})
            return
        self.task = self.entry.async_create_background_task(
            self.hass, self._async_publish(route), "vegvesen route source matching"
        )

    async def _async_publish(self, route: RouteCoordinator) -> None:
        geometry = route.subentry.data["geometry"]
        payload: dict[str, Any] = {"geometry": geometry}
        for kind, coordinator in self.entry.runtime_data.sources.items():
            if not self.msg.get(f"show_{kind}"):
                continue
            status = (
                "unavailable"
                if not coordinator.last_update_success
                else "loading"
                if coordinator.data is None or not coordinator.cache.fresh
                else "ready"
            )
            records = []
            if status == "ready":
                records = await self.hass.async_add_executor_job(
                    matching_sources,
                    geometry,
                    self.msg.get(
                        "camera_distance_m"
                        if kind == "cameras"
                        else "weather_distance_m",
                        250,
                    ),
                    coordinator.data,
                )
            payload[kind] = {
                "status": status,
                "items": [source_record(source) for source in records],
            }
        self.send({"data": payload})

    @callback
    def close(self) -> None:
        """Detach polling when the last map leaves; cancel obsolete payloads."""
        if self.task:
            self.task.cancel()
            self.task = None
        for remove in self.removers:
            remove()
        self.removers.clear()
        self.route = None


@dataclass(frozen=True, slots=True)
class CameraFrame:
    """One metadata/image outcome, including explicit request failure."""

    camera: RoadCamera | None
    image: bytes | None


class CameraFrames:
    """Coalesce on-demand images across routes; no background fetching or entities."""

    def __init__(self, client: VegvesenApiClient) -> None:
        """Bound both cache size and concurrent source requests."""
        self.client = client
        self._frames: OrderedDict[str, tuple[float, CameraFrame]] = OrderedDict()
        self._locks: dict[str, tuple[asyncio.Lock, int]] = {}
        self._semaphore = asyncio.Semaphore(4)

    async def async_get(self, source_id: str) -> CameraFrame:
        """Refresh selected metadata and still at most once per minute, failures too."""
        lock, users = self._locks.get(source_id, (asyncio.Lock(), 0))
        self._locks[source_id] = lock, users + 1
        try:
            async with lock:
                if (cached := self._frames.get(source_id)) and cached[0] > monotonic():
                    self._frames.move_to_end(source_id)
                    return cached[1]
                camera = None
                image = None
                try:
                    async with (
                        asyncio.timeout(REQUEST_TIMEOUT + IMAGE_REQUEST_TIMEOUT),
                        self._semaphore,
                    ):
                        cameras = await self.client.async_get_cameras({source_id})
                        camera = cameras.get(source_id)
                        if camera and camera.can_fetch_image and camera.image_url:
                            image = await self.client.async_get_image(camera.image_url)
                except (VegvesenApiError, TimeoutError):
                    pass
                frame = CameraFrame(camera, image)
                self._frames[source_id] = monotonic() + 60, frame
                self._frames.move_to_end(source_id)
                # Transport is bounded to 5 MiB/image; keep at most 16 frames.
                while len(self._frames) > 16:  # noqa: PLR2004
                    self._frames.popitem(last=False)
                return frame
        finally:
            _, users = self._locks[source_id]
            if users == 1:
                self._locks.pop(source_id, None)
            else:
                self._locks[source_id] = lock, users - 1
