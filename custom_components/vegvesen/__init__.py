"""Statens vegvesen integration, based on ludeeus/integration_blueprint (MIT)."""

from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import VegvesenApiClient
from .const import (
    CONF_CAMERA_ID,
    CONF_STATION_ID,
    SUBENTRY_CAMERA,
    SUBENTRY_WEATHER_STATION,
)
from .coordinator import CameraCoordinator, WeatherCoordinator
from .data import VegvesenData
from .route_api import RouteApiClient
from .route_coordinator import RouteCoordinator
from .route_services import async_setup_route_service

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import VegvesenConfigEntry

PLATFORMS = [Platform.SENSOR, Platform.CAMERA]


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
    route_client = RouteApiClient(async_get_clientsession(hass))
    routes = {
        s.subentry_id: RouteCoordinator(hass, entry, s, route_client)
        for s in entry.subentries.values()
        if s.subentry_type == "route"
    }
    entry.runtime_data = VegvesenData(
        client=client, weather=coordinator, cameras=cameras, routes=routes
    )
    active = [
        resource
        for resource, ids in ((coordinator, station_ids), (cameras, camera_ids))
        if ids
    ]
    active.extend(routes.values())
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
    entry.async_on_unload(
        entry.add_update_listener(
            partial(_async_reload_entry, runtime=entry.runtime_data)
        )
    )
    async_setup_route_service(hass, entry)
    return True


async def _async_reload_entry(
    hass: HomeAssistant, entry: VegvesenConfigEntry, *, runtime: VegvesenData
) -> None:
    """Coalesce a batch's update callbacks into one parent reload."""
    if runtime.reload_pending:
        return
    runtime.reload_pending = True
    try:
        # HA starts listeners eagerly. Let the synchronous batch finish before
        # taking its snapshot or unloading resources.
        await asyncio.sleep(0)
        while True:
            subentries = {
                key: (value.data, value.title)
                for key, value in entry.subentries.items()
            }
            if not await hass.config_entries.async_reload(entry.entry_id):
                break
            # A later selection can arrive while setup is awaiting source I/O,
            # before its new update listener has been installed.
            if subentries == {
                key: (value.data, value.title)
                for key, value in entry.subentries.items()
            }:
                break
    finally:
        runtime.reload_pending = False


async def async_unload_entry(hass: HomeAssistant, entry: VegvesenConfigEntry) -> bool:
    """Unload entities; HA cancels the entry's coordinator and listeners."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
