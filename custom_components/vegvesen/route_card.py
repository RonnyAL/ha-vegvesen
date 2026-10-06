"""Supported dashboard resource and subscriptions to complete cached forecasts."""

from __future__ import annotations

import asyncio
import base64
from functools import partial
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Any, cast

import voluptuous as vol
from homeassistant.auth.permissions.const import POLICY_READ
from homeassistant.components import frontend, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration

from .api import VegvesenApiError, VegvesenRateLimitError
from .const import CAMERA_UPDATE_INTERVAL, DOMAIN
from .route_sensor import ROUTE_SENSORS
from .route_services import forecast_hour
from .route_sources import CameraFrame, SourceWatch, matching_sources, source_record
from .route_summary import category_summary, highest_slip_risk

if TYPE_CHECKING:
    from homeassistant.core import Event, HomeAssistant

    from .data import VegvesenConfigEntry
    from .route_coordinator import RouteCoordinator, RouteSnapshot


async def async_setup_route_card(hass: HomeAssistant) -> None:
    """Serve the bundled module and register its data API once per process."""
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
    websocket_api.async_register_command(hass, websocket_subscribe_route_sources)
    websocket_api.async_register_command(hass, websocket_route_camera)


async def async_register_route_card(
    hass: HomeAssistant, entry: VegvesenConfigEntry
) -> None:
    """Load the bundled card through HA's public custom-integration helper."""
    # Optional after-dependency: headless installations still expose source data.
    if "frontend" not in hass.config.components:
        return
    integration = await async_get_integration(hass, DOMAIN)
    url = f"/vegvesen/route-map/vegvesen-route-map.js?v={integration.version}"
    frontend.add_extra_js_url(hass, url)
    entry.async_on_unload(partial(frontend.remove_extra_js_url, hass, url))


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
def _resolve_device(
    hass: HomeAssistant, device_id: str
) -> tuple[VegvesenConfigEntry, str] | None:
    """Identify the saved route from its device, never a translated name/model."""
    registry = dr.async_get(hass)
    if (device := registry.async_get(device_id)) is None:
        return None
    for entry in hass.config_entries.async_entries(DOMAIN):
        if device not in dr.async_entries_for_config_entry(registry, entry.entry_id):
            continue
        for subentry in entry.subentries.values():
            if (
                subentry.subentry_type == "route"
                and (
                    DOMAIN,
                    f"route:{subentry.data['route_id']}",
                )
                in device.identifiers
            ):
                return cast("VegvesenConfigEntry", entry), subentry.subentry_id
    return None


@callback
def _selection(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> tuple[VegvesenConfigEntry, str | None] | None:
    """Accept a route device or a legacy sensor; retain legacy read restrictions."""
    if entity_id := msg.get("entity_id"):
        if not connection.user.permissions.check_entity(entity_id, POLICY_READ):
            connection.send_error(msg["id"], "unauthorized", "Entity access denied")
            return None
        if resolved := _resolve_route(hass, entity_id):
            return resolved[1], resolved[0].unique_id
    elif resolved_device := _resolve_device(hass, msg["device_id"]):
        return resolved_device[0], None
    connection.send_error(msg["id"], "invalid_route", "Select a Statens vegvesen route")
    return None


@callback
def _current_coordinator(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    entry: VegvesenConfigEntry,
    unique_id: str | None,
) -> tuple[RouteCoordinator | None, str | None, set[str]]:
    """Check identity and access again on each event, including after reloads."""
    registry = er.async_get(hass)
    if unique_id is not None:
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        resolved = _resolve_route(hass, entity_id) if entity_id else None
        if resolved is None or resolved[1] is not entry:
            return None, "unavailable", set()
        entity = resolved[0]
        entities = [entity]
        subentry_id = entity.config_subentry_id
        disabled = entity.disabled
    else:
        resolved_device = _resolve_device(hass, msg["device_id"])
        if resolved_device is None or resolved_device[0] is not entry:
            return None, "unavailable", set()
        subentry_id = resolved_device[1]
        device = dr.async_get(hass).async_get(msg["device_id"])
        disabled = device.disabled
        entities = [
            entity
            for entity in er.async_entries_for_device(
                registry, device.id, include_disabled_entities=True
            )
            if entity.config_entry_id == entry.entry_id
            and entity.config_subentry_id == subentry_id
            and _resolve_route(hass, entity.entity_id) is not None
        ]
    entity_ids = {entity.entity_id for entity in entities}
    # HA permissions are entity based. A route's registered sensors all expose
    # the same underlying forecast; any readable one grants access. Disabling a
    # sensor does not change its permissions or the device-based map selection.
    if not any(
        connection.user.permissions.check_entity(entity_id, POLICY_READ)
        for entity_id in entity_ids
    ):
        return None, "unauthorized", entity_ids
    coordinator = (
        entry.runtime_data.routes.get(subentry_id)
        if entry.state is ConfigEntryState.LOADED and not disabled
        else None
    )
    return coordinator, None, entity_ids


def _source_distance(value: Any) -> int:
    """Accept integer map proximity settings without coercion."""
    if type(value) is not int:
        raise vol.Invalid("Expected an integer distance")
    return value


_TARGET_SCHEMA = {
    vol.Exclusive("device_id", "route", msg="Select a device or a legacy entity"): str,
    vol.Exclusive("entity_id", "route", msg="Select a device or a legacy entity"): (
        cv.entity_id
    ),
}


@callback
def _payload(coordinator: RouteCoordinator | None) -> dict[str, Any]:
    if (
        coordinator is None
        or not coordinator.last_update_success
        or coordinator.data is None
    ):
        return {"error": "unavailable"}
    snapshot = coordinator.data
    return {"data": _snapshot_payload(coordinator, snapshot)}


@callback
def _snapshot_payload(
    coordinator: RouteCoordinator, snapshot: RouteSnapshot
) -> dict[str, Any]:
    """Use the same map representation for configured and requested forecast hours."""
    return {
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


@websocket_api.websocket_command(
    vol.All(
        vol.Schema(
            {
                **_TARGET_SCHEMA,
                vol.Required("type"): "vegvesen/route_map",
                vol.Optional("forecast_time"): cv.datetime,
            }
        ),
        cv.has_at_least_one_key("device_id", "entity_id"),
    )
)
@websocket_api.async_response
async def websocket_route_map(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Read cached state, or query an hour using the action's shared forecast cache."""
    if (selection := _selection(hass, connection, msg)) is None:
        return
    coordinator, error, _entity_ids = _current_coordinator(
        hass, connection, msg, *selection
    )
    if "forecast_time" in msg and coordinator is not None and not error:
        try:
            _, target = forecast_hour(msg["forecast_time"])
            snapshot = await coordinator.async_forecast(target)
        except asyncio.CancelledError:
            if not coordinator.forecasts_closed:
                raise
            connection.send_error(msg["id"], "unavailable", "Route unavailable")
            return
        except (ServiceValidationError, VegvesenApiError) as err:
            code = (
                "forecast_time_out_of_range"
                if isinstance(err, ServiceValidationError)
                else "forecast_rate_limited"
                if isinstance(err, VegvesenRateLimitError)
                else "forecast_request_failed"
            )
            connection.send_error(msg["id"], code, "Forecast unavailable")
            return
        current, error, _ = _current_coordinator(hass, connection, msg, *selection)
        if (
            error
            or current is not coordinator
            or selection[0].subentries.get(coordinator.subentry.subentry_id)
            is not coordinator.subentry
        ):
            connection.send_error(
                msg["id"], error or "unavailable", "Route unavailable"
            )
            return
        connection.send_result(msg["id"], _snapshot_payload(coordinator, snapshot))
        return
    payload = {"error": error} if error else _payload(coordinator)
    if error := payload.get("error"):
        connection.send_error(msg["id"], error, "Route unavailable")
    else:
        connection.send_result(msg["id"], payload["data"])


@websocket_api.websocket_command(
    vol.All(
        vol.Schema(
            {**_TARGET_SCHEMA, vol.Required("type"): "vegvesen/subscribe_route_map"}
        ),
        cv.has_at_least_one_key("device_id", "entity_id"),
    )
)
@callback
def websocket_subscribe_route_map(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Subscribe to complete forecast snapshots."""
    _subscribe_route(hass, connection, msg)


@websocket_api.websocket_command(
    vol.All(
        vol.Schema(
            {
                **_TARGET_SCHEMA,
                vol.Required("type"): "vegvesen/subscribe_route_sources",
                vol.Optional("show_cameras", default=False): bool,
                vol.Optional("show_weather", default=False): bool,
                vol.Optional("camera_distance_m", default=250): vol.All(
                    _source_distance, vol.Range(min=1, max=2000)
                ),
                vol.Optional("weather_distance_m", default=250): vol.All(
                    _source_distance, vol.Range(min=1, max=2000)
                ),
            }
        ),
        cv.has_at_least_one_key("device_id", "entity_id"),
    )
)
@callback
def websocket_subscribe_route_sources(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Discover route sources independently of forecast polling and availability."""
    _subscribe_route(hass, connection, msg)


@callback
def _subscribe_route(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Push changes even when sensor summaries stay equal; rebind after entry reload."""
    if (selection := _selection(hass, connection, msg)) is None:
        return
    entry, unique_id = selection
    registry = er.async_get(hass)
    _initial, error, entity_ids = _current_coordinator(
        hass, connection, msg, *selection
    )
    if error:
        connection.send_error(msg["id"], error, "Route access denied or unavailable")
        return
    coordinator = None
    remove_coordinator = None
    source_watch = None

    @callback
    def send(payload: dict[str, Any]) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], payload))

    @callback
    def publish() -> None:
        nonlocal coordinator, remove_coordinator, entity_ids
        new_coordinator, error, entity_ids = _current_coordinator(
            hass, connection, msg, entry, unique_id
        )
        if new_coordinator is not coordinator:
            if remove_coordinator:
                remove_coordinator()
            coordinator = new_coordinator
            remove_coordinator = (
                coordinator.async_add_listener(publish) if coordinator else None
            )
        if source_watch:
            source_watch.update(coordinator, error)
        else:
            send({"error": error} if error else _payload(coordinator))

    if msg["type"] == "vegvesen/subscribe_route_sources":
        source_watch = SourceWatch(hass, entry, msg, publish, send)

    @callback
    def registry_changed(event: Event) -> None:
        entity = registry.async_get(event.data["entity_id"])
        if (
            event.data["entity_id"] in entity_ids
            or event.data.get("changes", {}).get("entity_id") in entity_ids
            or (unique_id and entity and entity.unique_id == unique_id)
            or (
                msg.get("device_id") and entity and entity.device_id == msg["device_id"]
            )
        ):
            publish()

    @callback
    def device_changed(event: Event) -> None:
        if event.data["device_id"] == msg.get("device_id"):
            publish()

    remove_state = entry.async_on_state_change(publish)
    remove_registry = hass.bus.async_listen(
        er.EVENT_ENTITY_REGISTRY_UPDATED, registry_changed
    )
    remove_device = hass.bus.async_listen(
        dr.EVENT_DEVICE_REGISTRY_UPDATED, device_changed
    )

    @callback
    def unsubscribe() -> None:
        if source_watch:
            source_watch.close()
        if remove_coordinator:
            remove_coordinator()
        remove_state()
        remove_registry()
        remove_device()

    connection.subscriptions[msg["id"]] = unsubscribe
    connection.send_result(msg["id"])
    publish()


@websocket_api.websocket_command(
    vol.All(
        vol.Schema(
            {
                **_TARGET_SCHEMA,
                vol.Required("type"): "vegvesen/route_camera",
                vol.Required("source_id"): str,
                vol.Optional("camera_distance_m", default=250): vol.All(
                    _source_distance, vol.Range(min=1, max=2000)
                ),
            }
        ),
        cv.has_at_least_one_key("device_id", "entity_id"),
    )
)
@websocket_api.async_response
async def websocket_route_camera(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Read one discovered still through HA's authenticated thumbnail pattern."""
    if (selection := _selection(hass, connection, msg)) is None:
        return
    route, error, _ = _current_coordinator(hass, connection, msg, *selection)
    if error or route is None:
        connection.send_error(msg["id"], error or "unavailable", "Route unavailable")
        return
    entry, _ = selection
    catalogue = entry.runtime_data.sources["cameras"]
    camera = (catalogue.data or {}).get(msg["source_id"])
    if not catalogue.last_update_success or camera is None:
        connection.send_error(msg["id"], "unavailable", "Camera unavailable")
        return
    matches = await hass.async_add_executor_job(
        matching_sources,
        route.subentry.data["geometry"],
        msg["camera_distance_m"],
        {camera.source_id: camera},
    )
    if not matches:
        connection.send_error(msg["id"], "invalid_source", "Camera outside route")
        return
    # A manually configured camera already has polling and an in-memory image.
    manual = entry.runtime_data.cameras
    if (
        camera.source_id in manual.camera_ids
        and monotonic() - manual.refreshed_at < CAMERA_UPDATE_INTERVAL.total_seconds()
    ):
        snapshot = (
            manual.data.get(camera.source_id) if manual.last_update_success else None
        )
        frame = (
            CameraFrame(snapshot.camera, snapshot.image)
            if snapshot
            else CameraFrame(None, None)
        )
    else:
        frame = await entry.runtime_data.camera_frames.async_get(camera.source_id)
    current, error, _ = _current_coordinator(hass, connection, msg, *selection)
    if error or current is not route:
        connection.send_error(msg["id"], error or "unavailable", "Route unavailable")
        return
    connection.send_result(
        msg["id"],
        {
            "camera": source_record(frame.camera) if frame.camera else None,
            "content": base64.b64encode(frame.image).decode("ascii")
            if frame.image
            else None,
            "content_type": "image/jpeg",
        },
    )
