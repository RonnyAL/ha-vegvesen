"""Supported dashboard resource and subscriptions to complete cached forecasts."""

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
from .route_sensor import ROUTE_SENSORS
from .route_summary import category_summary, highest_slip_risk

if TYPE_CHECKING:
    from homeassistant.core import Event, HomeAssistant

    from .data import VegvesenConfigEntry
    from .route_coordinator import RouteCoordinator


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
    websocket_api.async_register_command(hass, websocket_subscribe_route_map)


@callback
def _resolve_route(
    hass: HomeAssistant, entity_id: str
) -> tuple[er.RegistryEntry, VegvesenConfigEntry] | None:
    """Resolve only real route sensors, independently of names or translations."""
    entity = er.async_get(hass).async_get(entity_id)
    entry = (
        hass.config_entries.async_get_entry(entity.config_entry_id)
        if entity and entity.config_entry_id
        else None
    )
    if (
        entity is None
        or entity.domain != "sensor"
        or entity.platform != DOMAIN
        or entry is None
        or entry.domain != DOMAIN
    ):
        return None
    subentry = entry.subentries.get(entity.config_subentry_id)
    if (
        subentry is None
        or subentry.subentry_type != "route"
        or entity.unique_id
        not in {
            f"route:{subentry.data['route_id']}:{description.key}"
            for description in ROUTE_SENSORS
        }
    ):
        return None
    return entity, cast("VegvesenConfigEntry", entry)


@callback
def _payload(coordinator: RouteCoordinator | None) -> dict[str, Any]:
    if (
        coordinator is None
        or not coordinator.last_update_success
        or coordinator.data is None
    ):
        return {"error": "unavailable"}
    snapshot = coordinator.data
    return {
        "data": {
            "name": coordinator.subentry.title,
            "geometry": coordinator.subentry.data["geometry"],
            "forecast_time": snapshot.forecast_time.isoformat(),
            "summary": {
                "highest_slip_risk": highest_slip_risk(snapshot),
                "slip_risk": category_summary(snapshot, "SLIP_RISK"),
                "road_condition": category_summary(snapshot, "ROAD_CONDITION"),
            },
            "segments": [
                {
                    "type": "Feature",
                    "id": record.source_id,
                    "geometry": record.geometry,
                    "properties": record.properties,
                }
                for record in snapshot.segments
            ],
        }
    }


@websocket_api.websocket_command(
    {
        vol.Required("type"): "vegvesen/route_map",
        vol.Required("entity_id"): cv.entity_id,
    }
)
@callback
def websocket_route_map(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Read the current snapshot without source I/O."""
    if not connection.user.permissions.check_entity(msg["entity_id"], POLICY_READ):
        connection.send_error(msg["id"], "unauthorized", "Entity access denied")
        return
    if (resolved := _resolve_route(hass, msg["entity_id"])) is None:
        connection.send_error(
            msg["id"], "invalid_route", "Select a route forecast sensor"
        )
        return
    entity, entry = resolved
    coordinator = (
        entry.runtime_data.routes.get(entity.config_subentry_id)
        if entry.state is ConfigEntryState.LOADED and not entity.disabled
        else None
    )
    payload = _payload(coordinator)
    if error := payload.get("error"):
        connection.send_error(msg["id"], error, "Route unavailable")
    else:
        connection.send_result(msg["id"], payload["data"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "vegvesen/subscribe_route_map",
        vol.Required("entity_id"): cv.entity_id,
    }
)
@callback
def websocket_subscribe_route_map(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Push changes even when sensor summaries stay equal; rebind after entry reload."""
    if not connection.user.permissions.check_entity(msg["entity_id"], POLICY_READ):
        connection.send_error(msg["id"], "unauthorized", "Entity access denied")
        return
    if (resolved := _resolve_route(hass, msg["entity_id"])) is None:
        connection.send_error(
            msg["id"], "invalid_route", "Select a route forecast sensor"
        )
        return
    entity, entry = resolved
    registry = er.async_get(hass)
    unique_id = entity.unique_id
    current_entity_id = entity.entity_id
    coordinator = None
    remove_coordinator = None

    @callback
    def publish() -> None:
        nonlocal coordinator, remove_coordinator, current_entity_id
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        current_entity_id = entity_id or current_entity_id
        current = _resolve_route(hass, entity_id) if entity_id else None
        allowed = entity_id is not None and connection.user.permissions.check_entity(
            entity_id, POLICY_READ
        )
        available = (
            current
            and not current[0].disabled
            and entry.state is ConfigEntryState.LOADED
        )
        new_coordinator = (
            entry.runtime_data.routes.get(current[0].config_subentry_id)
            if allowed and available
            else None
        )
        if new_coordinator is not coordinator:
            if remove_coordinator:
                remove_coordinator()
            coordinator = new_coordinator
            remove_coordinator = (
                coordinator.async_add_listener(publish) if coordinator else None
            )
        payload = (
            _payload(coordinator)
            if allowed
            else {"error": "unauthorized" if entity_id else "unavailable"}
        )
        connection.send_message(websocket_api.event_message(msg["id"], payload))

    @callback
    def registry_changed(event: Event) -> None:
        if (
            event.data["entity_id"] == current_entity_id
            or event.data.get("changes", {}).get("entity_id") == current_entity_id
        ):
            publish()

    remove_state = entry.async_on_state_change(publish)
    remove_registry = hass.bus.async_listen(
        er.EVENT_ENTITY_REGISTRY_UPDATED, registry_changed
    )

    @callback
    def unsubscribe() -> None:
        if remove_coordinator:
            remove_coordinator()
        remove_state()
        remove_registry()

    connection.subscriptions[msg["id"]] = unsubscribe
    connection.send_result(msg["id"])
    publish()
