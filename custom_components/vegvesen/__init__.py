"""Statens vegvesen integration, based on ludeeus/integration_blueprint (MIT)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import VegvesenApiClient
from .const import (
    CONF_CAMERA_ID,
    CONF_STATION_ID,
    DOMAIN,
    SUBENTRY_CAMERA,
    SUBENTRY_WEATHER_STATION,
)
from .coordinator import CameraCoordinator, WeatherCoordinator
from .data import VegvesenData
from .frontend import async_ensure_source_selector

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import VegvesenConfigEntry

PLATFORMS = [Platform.SENSOR, Platform.CAMERA]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    """Register this integration's UI before browsers load an existing setup."""
    await async_ensure_source_selector(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: VegvesenConfigEntry) -> bool:
    """Create entry resources and set up selected station entities."""
    client = VegvesenApiClient(async_get_clientsession(hass))
    station_ids = {
        subentry.data[CONF_STATION_ID]
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_WEATHER_STATION
    }
    coordinator = WeatherCoordinator(hass, entry, client, station_ids)
    camera_ids = {
        subentry.data[CONF_CAMERA_ID]
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_CAMERA
    }
    cameras = CameraCoordinator(hass, entry, client, camera_ids)
    entry.runtime_data = VegvesenData(
        client=client, weather=coordinator, cameras=cameras
    )
    active = [
        resource
        for resource, ids in ((coordinator, station_ids), (cameras, camera_ids))
        if ids
    ]
    results = await asyncio.gather(
        *(resource.async_config_entry_first_refresh() for resource in active),
        return_exceptions=True,
    )
    # Load a working family while the other recovers through its own coordinator.
    for result in results:
        if isinstance(result, BaseException) and not isinstance(
            result, ConfigEntryNotReady
        ):
            raise result
    if results and all(isinstance(result, ConfigEntryNotReady) for result in results):
        raise results[0]
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: VegvesenConfigEntry) -> None:
    """Reconcile additions and removals by reloading the parent entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: VegvesenConfigEntry) -> bool:
    """Unload entities; HA cancels the entry's coordinator and listeners."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
