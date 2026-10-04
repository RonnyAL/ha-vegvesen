"""Supported dashboard resource and authenticated access to cached map data."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import voluptuous as vol
from homeassistant.auth.permissions.const import POLICY_READ
from homeassistant.components import websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import VegvesenConfigEntry


async def async_setup_route_card(hass: HomeAssistant) -> None:
    """Ship a normal manually registered dashboard JS module, once per process."""
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                "/vegvesen/route-map",
                str(Path(__file__).with_name("frontend")),
                cache_headers=False,
            )
        ]
    )
    websocket_api.async_register_command(hass, websocket_route_map)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "vegvesen/route_map",
        vol.Required("entity_id"): cv.entity_id,
    }
)
@callback
def websocket_route_map(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Resolve a renamed image through its registry identity, without source I/O."""
    entity_id = msg["entity_id"]
    if not connection.user.permissions.check_entity(entity_id, POLICY_READ):
        connection.send_error(msg["id"], "unauthorized", "Entity access denied")
        return
    entity = er.async_get(hass).async_get(entity_id)
    entry = (
        hass.config_entries.async_get_entry(entity.config_entry_id)
        if entity and entity.config_entry_id
        else None
    )
    if (
        entity is None
        or entity.domain != "image"
        or entity.platform != DOMAIN
        or entry is None
        or entry.domain != DOMAIN
    ):
        connection.send_error(msg["id"], "invalid_route", "Select a route map entity")
        return
    entry = cast("VegvesenConfigEntry", entry)
    if entry.state is not ConfigEntryState.LOADED:
        connection.send_error(msg["id"], "unavailable", "Route unavailable")
        return
    coordinator = entry.runtime_data.routes.get(entity.config_subentry_id)
    if (
        coordinator is None
        or entity.unique_id != f"route:{coordinator.subentry.data['route_id']}:map"
        or entity.disabled
        or not coordinator.last_update_success
        or coordinator.data is None
    ):
        connection.send_error(msg["id"], "unavailable", "Route unavailable")
        return
    snapshot = coordinator.data
    connection.send_result(
        msg["id"],
        {
            "name": coordinator.subentry.title,
            "geometry": coordinator.subentry.data["geometry"],
            "forecast_time": snapshot.forecast_time.isoformat(),
            "segments": [
                {
                    "type": "Feature",
                    "id": record.source_id,
                    "geometry": record.geometry,
                    "properties": record.properties,
                }
                for record in snapshot.segments
            ],
        },
    )
