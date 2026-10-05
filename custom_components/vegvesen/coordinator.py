"""Poll weather and CCTV independently, with individual camera image failures."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    RoadCamera,
    VegvesenApiClient,
    VegvesenApiError,
    VegvesenRateLimitError,
    WeatherStation,
)
from .const import CAMERA_UPDATE_INTERVAL, DOMAIN, LOGGER, WEATHER_UPDATE_INTERVAL

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
        self._config_entry_id = entry.entry_id
        self.station_ids = frozenset(station_ids)
        self.data = {}

    async def _async_update_data(self) -> dict[str, WeatherStation]:
        """Replace data only after every requested page succeeds."""
        try:
            stations = await self.client.async_get_weather(self.station_ids)
        except VegvesenRateLimitError as err:
            raise UpdateFailed(str(err), retry_after=err.retry_after) from err
        except VegvesenApiError as err:
            raise UpdateFailed(str(err)) from err
        registry = dr.async_get(self.hass)
        # Entry-scoped identifiers work on both supported HA registry versions.
        devices_by_identifier = {
            identifier: device
            for device in dr.async_entries_for_config_entry(
                registry, self._config_entry_id
            )
            for identifier in device.identifiers
        }
        for station in stations.values():
            device = devices_by_identifier.get(
                (DOMAIN, f"weather_station:{station.source_id}")
            )
            if device is not None and device.name != station.name:
                registry.async_update_device(device.id, name=station.name)
        return stations


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
        self.refreshed_at = 0.0
        self.data = {}
        self._image_semaphore = asyncio.Semaphore(4)

    async def _async_update_data(self) -> dict[str, CameraSnapshot]:
        """Track cache age even when all entity listeners are later disabled."""
        try:
            return await self._async_fetch_data()
        finally:
            self.refreshed_at = monotonic()

    async def _async_fetch_data(self) -> dict[str, CameraSnapshot]:
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
        try:
            async with self._image_semaphore:
                image = await self.client.async_get_image(camera.image_url)
        except VegvesenApiError as err:
            return CameraSnapshot(camera, None, str(err))
        return CameraSnapshot(camera, image)
