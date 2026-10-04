"""Statens vegvesen integration, based on ludeeus/integration_blueprint (MIT)."""

from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_CAMERA_ID,
    CONF_STATION_ID,
    DOMAIN,
    SUBENTRY_CAMERA,
    SUBENTRY_WEATHER_STATION,
)
from .coordinator import CameraCoordinator, WeatherCoordinator
from .data import VegvesenData
from .discovery import async_get_discovery
from .route_card import async_register_route_card, async_setup_route_card
from .route_coordinator import RouteCoordinator
from .route_services import async_setup_route_service

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

    from .data import VegvesenConfigEntry

PLATFORMS = [Platform.SENSOR, Platform.CAMERA]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:  # noqa: ARG001
    """Register the route action independently of entry setup and reloads."""
    async_setup_route_service(hass)
    await async_setup_route_card(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: VegvesenConfigEntry) -> bool:
    """Create entry resources and set up selected station entities."""
    await async_register_route_card(hass, entry)
    shared = async_get_discovery(hass)
    client = shared.client
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
    route_client = shared.route_client
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
    # Retire only this integration's experimental route images. Saved route
    # devices and sensor identities remain intact; previews have no entities.
    registry = er.async_get(hass)
    retired_ids = {
        f"route:{s.data['route_id']}:map"
        for s in entry.subentries.values()
        if s.subentry_type == "route"
    }
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            entity.domain == "image"
            and entity.platform == DOMAIN
            and entity.unique_id in retired_ids
        ):
            registry.async_remove(entity.entity_id)
    entry.async_on_unload(
        entry.add_update_listener(
            partial(_async_reload_entry, runtime=entry.runtime_data)
        )
    )
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
