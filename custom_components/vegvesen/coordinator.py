"""Poll weather and CCTV independently, with individual camera image failures."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    RoadCamera,
    VegvesenApiClient,
    VegvesenApiError,
    VegvesenRateLimitError,
    WeatherStation,
)
from .const import CAMERA_UPDATE_INTERVAL, LOGGER, WEATHER_UPDATE_INTERVAL

if TYPE_CHECKING:
    from collections.abc import Collection

    from homeassistant.core import HomeAssistant

    from .data import VegvesenConfigEntry


class WeatherCoordinator(DataUpdateCoordinator[dict[str, WeatherStation]]):
    """Publish complete snapshots, letting HA handle failures and recovery."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: VegvesenConfigEntry,
        client: VegvesenApiClient,
        station_ids: Collection[str],
    ) -> None:
        """Initialize weather-only polling and immutable selection."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name="Statens vegvesen weather",
            update_interval=WEATHER_UPDATE_INTERVAL,
            always_update=False,
        )
        self.client = client
        self.station_ids = frozenset(station_ids)
        self.data = {}

    async def _async_update_data(self) -> dict[str, WeatherStation]:
        """Replace data only after every requested page succeeds."""
        try:
            return await self.client.async_get_weather(self.station_ids)
        except VegvesenRateLimitError as err:
            raise UpdateFailed(str(err), retry_after=err.retry_after) from err
        except VegvesenApiError as err:
            raise UpdateFailed(str(err)) from err


@dataclass(frozen=True, slots=True)
class CameraSnapshot:
    """A complete metadata record and its latest image request outcome."""

    camera: RoadCamera
    image: bytes | None
    image_error: str | None = None


class CameraCoordinator(DataUpdateCoordinator[dict[str, CameraSnapshot]]):
    """Cache selected stills; an image error affects only that camera."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: VegvesenConfigEntry,
        client: VegvesenApiClient,
        camera_ids: Collection[str],
    ) -> None:
        """Initialize CCTV polling separately from weather."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name="Statens vegvesen cameras",
            update_interval=CAMERA_UPDATE_INTERVAL,
            always_update=False,
        )
        self.client = client
        self.camera_ids = frozenset(camera_ids)
        self.data = {}
        self._image_semaphore = asyncio.Semaphore(4)
        self._image_retry_at: dict[str, float] = {}

    async def _async_update_data(self) -> dict[str, CameraSnapshot]:
        """Complete metadata pagination before issuing any image requests."""
        try:
            cameras = await self.client.async_get_cameras(self.camera_ids)
        except VegvesenRateLimitError as err:
            raise UpdateFailed(str(err), retry_after=err.retry_after) from err
        except VegvesenApiError as err:
            raise UpdateFailed(str(err)) from err
        snapshots = await asyncio.gather(
            *(self._async_get_snapshot(camera) for camera in cameras.values())
        )
        return {snapshot.camera.source_id: snapshot for snapshot in snapshots}

    async def _async_get_snapshot(self, camera: RoadCamera) -> CameraSnapshot:
        """Respect source availability and image-specific retry headers."""
        if not camera.can_fetch_image or camera.image_url is None:
            return CameraSnapshot(camera, None)
        if monotonic() < self._image_retry_at.get(camera.source_id, 0):
            return CameraSnapshot(camera, None, "Camera image rate limited")
        try:
            async with self._image_semaphore:
                image = await self.client.async_get_image(camera.image_url)
        except VegvesenRateLimitError as err:
            self._image_retry_at[camera.source_id] = monotonic() + err.retry_after
            return CameraSnapshot(camera, None, str(err))
        except VegvesenApiError as err:
            return CameraSnapshot(camera, None, str(err))
        self._image_retry_at.pop(camera.source_id, None)
        return CameraSnapshot(camera, image)
