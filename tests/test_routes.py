"""Route geometry, atomic forecasts, native flows and lifecycle tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER, ConfigSubentry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry
from yarl import URL

from custom_components.vegvesen.api import VegvesenApiError, VegvesenRateLimitError
from custom_components.vegvesen.const import DOMAIN
from custom_components.vegvesen.route_api import (
    FORECAST_URL,
    ROUTING_URL,
    RouteApiClient,
    RoutePointError,
    parse_forecast,
    parse_routes,
)
from custom_components.vegvesen.route_geometry import make_corridor

from .helpers import finish_progress, menu_action, page

if TYPE_CHECKING:
    from aioresponses import aioresponses
    from homeassistant.core import HomeAssistant


def routing_url(data: dict[str, Any]) -> str:
    """Match the verified lon/lat request, with geometry explicitly requested."""
    return str(
        URL(ROUTING_URL).with_query(
            {
                "Stops": ";".join(
                    f"{data[p]['longitude']},{data[p]['latitude']}"
                    for p in ("start", "end")
                ),
                "InputSRS": "EPSG_4326",
                "OutputSRS": "EPSG_4326",
                "ReturnFields": "Geometry",
                "Lang": "Norwegian",
            }
        )
    )


def forecast_url(bbox: str, target: datetime, start: int | None = None) -> str:
    """Preserve the spatial/time query across pagination."""
    params = {
        "f": "application/json",
        "limit": "500",
        "bbox": bbox,
        "filter-lang": "cql2-text",
        "filter": f"FORECAST_TIME = TIMESTAMP('{target.isoformat()}')",
    }
    if start is not None:
        params["startIndex"] = str(start)
    return str(URL(FORECAST_URL).with_query(params))


async def submit_manual_route(manager: Any, result: Any, data: dict[str, Any]) -> Any:
    """Exercise settings followed by only the requested manual location fields."""
    if result["step_id"] == "route_settings":
        result = await manager.async_configure(
            result["flow_id"],
            {
                **{k: data[k] for k in ("name", "corridor_m", "forecast_hours")},
                "start_source": "map",
                "end_source": "map",
            },
        )
        result = await finish_progress(manager, result)
        if result.get("errors"):
            return result
    assert result["step_id"] == "route_locations"
    return await finish_progress(
        manager,
        await manager.async_configure(
            result["flow_id"], {k: data[k] for k in ("start", "end")}
        ),
    )


def source_entity(hass: HomeAssistant, key: str) -> str:
    """Resolve stable route entity identity independent of its translated label."""
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"route:example-route:{key}"
    )
    assert entity_id
    return entity_id


def test_routing_geometry_and_filtering(
    routing: dict[str, Any], forecasts: list[dict[str, Any]]
) -> None:
    """The public route produces a real corridor and excludes unrelated roads."""
    route = parse_routes(routing)[0]
    assert route.name == "E6/E39"
    assert route.length == 41811
    corridor = make_corridor(route.geometry, 100)
    assert corridor.intersects(forecasts[0]["geometry"])
    assert not corridor.intersects(
        {"type": "LineString", "coordinates": [[9.9, 63.4], [9.91, 63.4]]}
    )
    assert not corridor.intersects(None)
    separated = make_corridor(
        {
            "type": "MultiLineString",
            "coordinates": [[[10, 60], [10.01, 60]], [[10.1, 60], [10.11, 60]]],
        },
        100,
    )
    assert not separated.intersects(
        {"type": "LineString", "coordinates": [[10.05, 60], [10.06, 60]]}
    )


@pytest.mark.parametrize(
    "damage",
    ["empty", "missing_part", "coordinate", "temperature", "timestamp", "unit"],
)
def test_malformed_source_rejected(
    routing: dict[str, Any], forecasts: list[dict[str, Any]], damage: str
) -> None:
    """Schema errors never become usable routes or plausible-looking forecasts."""
    if damage in {"empty", "missing_part", "coordinate"}:
        if damage == "empty":
            routing["routes"][0]["features"] = []
        elif damage == "missing_part":
            routing["routes"][0]["features"][0]["geometry"] = None
        else:
            routing["routes"][0]["features"][0]["geometry"]["coordinates"][0][0] = (
                float("nan")
            )
        with pytest.raises(VegvesenApiError):
            parse_routes(routing)
    else:
        props = forecasts[0]["properties"]
        props.update(
            {
                "temperature": {"ROAD_TEMPERATURE": "cold"},
                "timestamp": {"FORECAST_TIME": "2026-10-04T00:00:00"},
                "unit": {"ROAD_TEMPERATURE_UOM": "F"},
            }[damage]
        )
        with pytest.raises(VegvesenApiError):
            parse_forecast(forecasts[0])


@pytest.mark.parametrize(
    "failure",
    ["http", "incomplete", "changed_query", "wrong_hour", "duplicate", "success"],
)
async def test_atomic_forecast_pages(
    hass: HomeAssistant,
    mock_http: aioresponses,
    forecasts: list[dict[str, Any]],
    failure: str,
) -> None:
    """All pages and the requested forecast time must validate before publication."""
    target = datetime.fromisoformat(
        forecasts[0]["properties"]["FORECAST_TIME"]
    ).astimezone(UTC)
    bbox = "9.8,63.3,10.4,63.5"
    next_url = forecast_url(bbox, target, 1)
    first = page(forecasts[:1], matched=2, next_url=next_url)
    if failure == "incomplete":
        first["links"] = []
    if failure == "changed_query":
        first["links"][0]["href"] = next_url.replace("9.8", "9.7")
    if failure == "wrong_hour":
        first["features"][0]["properties"]["FORECAST_TIME"] = (
            target + timedelta(hours=1)
        ).isoformat()
    mock_http.get(forecast_url(bbox, target), payload=first)
    if failure == "http":
        mock_http.get(next_url, status=503)
    else:
        mock_http.get(
            next_url,
            payload=page(
                forecasts[:1] if failure == "duplicate" else forecasts[1:2], matched=2
            ),
        )
    client = RouteApiClient(async_get_clientsession(hass))
    if failure == "success":
        result = await client.async_forecasts(bbox, target)
        assert len(result) == 2
    else:
        with pytest.raises(VegvesenApiError):
            await client.async_forecasts(bbox, target)


@pytest.mark.parametrize("kind", ["parent", "subentry"])
async def test_route_flow(  # noqa: PLR0915
    hass: HomeAssistant,
    mock_http: aioresponses,
    routing: dict[str, Any],
    route_data: dict[str, Any],
    kind: str,
) -> None:
    """Native route configuration saves only after an editable overview confirmation."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="public_service", data={})
    with patch("custom_components.vegvesen.async_setup_entry", return_value=True):
        if kind == "parent":
            manager = hass.config_entries.flow
            result = await manager.async_init(DOMAIN, context={"source": SOURCE_USER})
            result = await menu_action(manager, result, "route")
        else:
            entry.add_to_hass(hass)
            manager = hass.config_entries.subentries
            result = await manager.async_init(
                (entry.entry_id, "route"), context={"source": SOURCE_USER}
            )
        assert result["step_id"] == "route_settings"
        assert result["data_schema"].schema["start_source"].selector_type == "select"
        data = {
            k: route_data[k]
            for k in ("name", "start", "end", "corridor_m", "forecast_hours")
        }
        mock_http.get(routing_url(route_data), payload=routing)
        result = await submit_manual_route(manager, result, data)
        assert result["type"] is FlowResultType.MENU
        result = await menu_action(manager, result, "route_settings")
        data["corridor_m"] = 200
        result = await submit_manual_route(manager, result, data)
        assert (
            len(mock_http.requests) == 1
        )  # Changing the corridor never recalculates the road.
        assert not entry.subentries
        result = await menu_action(manager, result, "route_choice")
        result = await manager.async_configure(result["flow_id"], {"route": "0"})
        result = await menu_action(manager, result, "route_save")
        await hass.async_block_till_done()
        assert result["type"] is FlowResultType.CREATE_ENTRY
        if kind == "parent":
            entry = result["result"]
        subentry = next(iter(entry.subentries.values()))
        assert subentry.data["corridor_m"] == 200
        assert subentry.data["geometry"] == route_data["geometry"]
        assert subentry.unique_id == f"route:{subentry.data['route_id']}"
    # Reconfiguration keeps identity, and can retain the stored route offline.
    original_id = subentry.subentry_id
    manager = hass.config_entries.subentries
    result = await manager.async_init(
        (entry.entry_id, "route"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": original_id},
    )
    result = await menu_action(manager, result, "route_settings")
    data["name"] = "Renamed route"
    result = await submit_manual_route(manager, result, data)
    result = await menu_action(manager, result, "route_save")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[original_id].title == "Renamed route"
    assert entry.subentries[original_id].unique_id == subentry.unique_id
    assert len(mock_http.requests) == 1
    result = await manager.async_init(
        (entry.entry_id, "route"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": original_id},
    )
    mock_http.get(routing_url(data), payload=routing)
    result = await menu_action(manager, result, "route_recalculate")
    assert result["step_id"] == "route_overview"
    result = await menu_action(manager, result, "route_save")
    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[original_id].data["route_id"] == subentry.data["route_id"]
    assert sum(len(calls) for calls in mock_http.requests.values()) == 2


async def test_forecast_entities_and_recovery(  # noqa: PLR0915
    hass: HomeAssistant,
    mock_http: aioresponses,
    forecasts: list[dict[str, Any]],
    route_data: dict[str, Any],
    freezer: Any,
) -> None:
    """Verify missing/zero/unusual values, categories, recovery and unloading."""
    target = datetime.fromisoformat(
        forecasts[0]["properties"]["FORECAST_TIME"]
    ).astimezone(UTC)
    freezer.move_to(target - timedelta(minutes=55))
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="public_service",
        data={},
        subentries_data=[
            {
                "subentry_type": "route",
                "unique_id": "route:example-route",
                "title": route_data["name"],
                "data": route_data,
            }
        ],
    )
    entry.add_to_hass(hass)
    forecasts[0]["properties"].update(
        {"ROAD_TEMPERATURE": 0, "ROAD_CONDITION": "IceOrFrost", "SLIP_RISK": "high"}
    )
    forecasts[1]["properties"].update(
        {
            "ROAD_TEMPERATURE": -123.4,
            "ROAD_CONDITION": "FutureSourceCode",
            "SLIP_RISK": None,
        }
    )
    forecasts[2]["properties"].update(
        {"ROAD_TEMPERATURE": None, "ROAD_CONDITION": None, "SLIP_RISK": "ErrorOrNoData"}
    )
    bbox = make_corridor(route_data["geometry"], 100).bbox
    url = forecast_url(bbox, target)
    mock_http.get(url, payload=page(forecasts))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = next(iter(entry.runtime_data.routes.values()))
    assert len(hass.states.async_all("sensor")) == 6
    assert (
        hass.states.get(source_entity(hass, "minimum_road_temperature")).state
        == "-123.4"
    )
    assert hass.states.get(source_entity(hass, "maximum_road_temperature")).state == "0"
    condition = hass.states.get(source_entity(hass, "road_condition"))
    assert condition.state == "partial_data"
    assert condition.attributes["source_categories"] == {
        "IceOrFrost": 1,
        "FutureSourceCode": 1,
    }
    assert condition.attributes["missing_segments"] == 1
    risk = hass.states.get(source_entity(hass, "slip_risk"))
    assert risk.state == "partial_data"
    assert risk.attributes["missing_segments"] == 2
    assert risk.attributes["source_categories"]["ErrorOrNoData"] == 1
    device = dr.async_get(hass).async_get(
        er.async_get(hass).async_get(condition.entity_id).device_id
    )
    assert device
    response = await hass.services.async_call(
        DOMAIN,
        "get_route_forecasts",
        {"device_id": device.id},
        blocking=True,
        return_response=True,
    )
    assert response["segments"][1]["properties"]["ROAD_TEMPERATURE"] == -123.4
    mock_http.get(url, status=429, headers={"Retry-After": "120"})
    await coordinator.async_refresh()
    assert coordinator.last_exception.retry_after == 120
    assert hass.states.get(condition.entity_id).state == STATE_UNAVAILABLE
    # Failed snapshots must not be returned as the latest successful result.
    freezer.tick(timedelta(seconds=121))
    mock_http.get(url, status=503)
    await coordinator.async_refresh()
    assert hass.states.get(condition.entity_id).state == STATE_UNAVAILABLE
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "get_route_forecasts",
            {"device_id": device.id},
            blocking=True,
            return_response=True,
        )
    mock_http.get(url, payload=page([]))
    await coordinator.async_refresh()
    assert hass.states.get(condition.entity_id).state == STATE_UNKNOWN
    assert hass.states.get(source_entity(hass, "forecast_segments")).state == "0"
    mock_http.get(url, payload=page(forecasts[:1]))
    await coordinator.async_refresh()
    assert hass.states.get(condition.entity_id).state == "ice_or_frost"
    mock_http.get(url, payload=page(forecasts[:2]))
    await coordinator.async_refresh()
    assert hass.states.get(condition.entity_id).state == "mixed"
    mock_http.get(url, payload=page(forecasts[1:2]))
    await coordinator.async_refresh()
    assert hass.states.get(condition.entity_id).state == "FutureSourceCode"
    assert hass.states.get(source_entity(hass, "slip_risk")).state == STATE_UNKNOWN
    mock_http.get(url, payload=page(forecasts[2:]))
    await coordinator.async_refresh()
    assert hass.states.get(condition.entity_id).state == STATE_UNKNOWN
    assert (
        hass.states.get(source_entity(hass, "minimum_road_temperature")).state
        == STATE_UNKNOWN
    )
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert coordinator._shutdown_requested
    assert hass.services.has_service(DOMAIN, "get_route_forecasts")
    with pytest.raises(ServiceValidationError, match="unavailable"):
        await hass.services.async_call(
            DOMAIN,
            "get_route_forecasts",
            {"device_id": device.id},
            blocking=True,
            return_response=True,
        )


@pytest.mark.parametrize("failure", ["http", "no_route", "invalid_point"])
async def test_route_settings_failure_and_retry(
    hass: HomeAssistant,
    mock_http: aioresponses,
    routing: dict[str, Any],
    route_data: dict[str, Any],
    failure: str,
) -> None:
    """Failed settings stay editable and cannot reuse geometry for different stops."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="public_service", data={})
    entry.add_to_hass(hass)
    manager = hass.config_entries.subentries
    result = await manager.async_init(
        (entry.entry_id, "route"), context={"source": SOURCE_USER}
    )
    data = {
        k: route_data[k]
        for k in ("name", "start", "end", "corridor_m", "forecast_hours")
    }
    bad = deepcopy(data)
    if failure == "http":
        mock_http.get(routing_url(data), status=503)
    elif failure == "no_route":
        mock_http.get(routing_url(data), payload={"routes": []})
    else:
        bad["start"]["latitude"] = 100
    result = await submit_manual_route(manager, result, bad)
    assert result["type"] is FlowResultType.FORM
    assert next(iter(result["errors"].values())) == (
        "cannot_connect"
        if failure == "http"
        else "no_route"
        if failure == "no_route"
        else "invalid_route"
    )
    assert not entry.subentries
    mock_http.get(routing_url(data), payload=routing)
    result = await submit_manual_route(manager, result, data)
    assert result["type"] is FlowResultType.MENU
    result = await menu_action(manager, result, "route_settings")
    bad = deepcopy(data)
    bad["end"]["longitude"] += 0.001
    bad["start"]["latitude"] = 100
    result = await submit_manual_route(manager, result, bad)
    assert result["errors"]
    bad["name"] = "Changed destination"
    bad["start"] = data["start"]
    mock_http.get(routing_url(bad), payload=routing)
    result = await submit_manual_route(manager, result, bad)
    assert result["type"] is FlowResultType.MENU
    assert sum(len(calls) for calls in mock_http.requests.values()) == (
        3 if failure in {"http", "no_route"} else 2
    )


async def test_routes_weather_isolation_and_removal(
    hass: HomeAssistant,
    mock_http: aioresponses,
    forecasts: list[dict[str, Any]],
    route_data: dict[str, Any],
    config_entry: MockConfigEntry,
    features: list[dict[str, Any]],
    freezer: Any,
) -> None:
    """Overlapping routes are independent and never create duplicate source devices."""
    from .helpers import weather_url  # noqa: PLC0415

    target = datetime.fromisoformat(
        forecasts[0]["properties"]["FORECAST_TIME"]
    ).astimezone(UTC)
    freezer.move_to(target - timedelta(minutes=55))
    config_entry.add_to_hass(hass)
    for route_id in ("first", "second"):
        hass.config_entries.async_add_subentry(
            config_entry,
            ConfigSubentry(
                subentry_type="route",
                unique_id=f"route:{route_id}",
                title=route_id,
                data={**route_data, "route_id": route_id},
            ),
        )
    route_entries = [
        s for s in config_entry.subentries.values() if s.subentry_type == "route"
    ]
    url = forecast_url(make_corridor(route_data["geometry"], 100).bbox, target)
    mock_http.get(weather_url(("1629006", "1629013")), payload=page(features[:2]))
    mock_http.get(url, payload=page(forecasts))
    mock_http.get(url, status=503)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    routes = config_entry.runtime_data.routes
    # Corridor construction uses an executor, so identical concurrent requests
    # may reach the mock in either order. Exactly one route must fail.
    assert sum(route.last_update_success for route in routes.values()) == 1
    failed = next(route for route in routes.values() if not route.last_update_success)
    assert config_entry.runtime_data.weather.last_update_success
    registry = er.async_get(hass)
    station_id = registry.async_get_entity_id(
        "sensor", DOMAIN, "weather_station:1629006:air_temperature"
    )
    station_device = registry.async_get(station_id).device_id
    assert (
        len(
            dr.async_entries_for_config_entry(dr.async_get(hass), config_entry.entry_id)
        )
        == 4
    )
    assert len(registry.entities) == 18
    mock_http.get(url, payload=page(forecasts))
    await failed.async_refresh()
    assert failed.last_update_success
    # Removing a route does not remove the physical stations or the other route.
    mock_http.get(weather_url(("1629006", "1629013")), payload=page(features[:2]))
    mock_http.get(url, payload=page(forecasts))
    hass.config_entries.async_remove_subentry(
        config_entry, route_entries[0].subentry_id
    )
    await hass.async_block_till_done()
    assert routes[route_entries[0].subentry_id]._shutdown_requested
    assert len(config_entry.runtime_data.routes) == 1
    assert registry.async_get(station_id).device_id == station_device
    assert len(registry.entities) == 11
    # Editing a loaded route reloads its corridor without replacing entities.
    retained = route_entries[1]
    original = config_entry.runtime_data.routes[retained.subentry_id]
    identities = {e.unique_id: e.entity_id for e in registry.entities.values()}
    changed = {**retained.data, "corridor_m": 200}
    mock_http.get(weather_url(("1629006", "1629013")), payload=page(features[:2]))
    mock_http.get(
        forecast_url(make_corridor(changed["geometry"], 200).bbox, target),
        payload=page(forecasts),
    )
    hass.config_entries.async_update_subentry(
        config_entry, retained, data=changed, title="Updated route"
    )
    await hass.async_block_till_done()
    assert original._shutdown_requested
    replacement = config_entry.runtime_data.routes[retained.subentry_id]
    assert replacement.subentry.data["corridor_m"] == 200
    assert replacement.last_update_success
    assert identities == {e.unique_id: e.entity_id for e in registry.entities.values()}


@pytest.mark.parametrize("code", [9005, 9200, 9201, 9299, 9008, 9009, 9999, None])
@pytest.mark.parametrize("key", ["code", "Code"])
async def test_routing_error_codes(
    hass: HomeAssistant,
    mock_http: aioresponses,
    route_data: dict[str, Any],
    code: int | None,
    key: str,
) -> None:
    """A routing overload is a failed request, not an absent road connection."""
    mock_http.get(routing_url(route_data), status=404, payload={key: code})
    client = RouteApiClient(async_get_clientsession(hass))
    stops = [route_data["start"], route_data["end"]]
    if code in {9200, 9201}:
        with pytest.raises(RoutePointError) as error:
            await client.async_routes(stops)
        assert error.value.endpoint == ("start" if code == 9200 else "end")
    elif code in {9005, 9299}:
        assert await client.async_routes(stops) == []
    else:
        with pytest.raises(VegvesenApiError):
            await client.async_routes(stops)


async def test_routing_rate_limit(
    hass: HomeAssistant,
    mock_http: aioresponses,
    route_data: dict[str, Any],
) -> None:
    """Preserve the server's retry hint without retrying in a tight loop."""
    mock_http.get(routing_url(route_data), status=429, headers={"Retry-After": "120"})
    with pytest.raises(VegvesenRateLimitError) as error:
        await RouteApiClient(async_get_clientsession(hass)).async_routes(
            [route_data["start"], route_data["end"]]
        )
    assert error.value.retry_after == 120


def test_segment_zero(forecasts: list[dict[str, Any]]) -> None:
    """A zero source identifier and zero temperature are both real values."""
    forecasts[0]["properties"].update({"ROAD_SEGMENT_ID": 0, "ROAD_TEMPERATURE": 0})
    forecast = parse_forecast(forecasts[0])
    assert forecast.source_id.startswith("0:")
    assert forecast.properties["ROAD_TEMPERATURE"] == 0


@pytest.mark.parametrize("kind", ["parent", "subentry"])
@pytest.mark.parametrize("mixed", [False, True])
async def test_zone_endpoints(  # noqa: PLR0915
    hass: HomeAssistant,
    mock_http: aioresponses,
    routing: dict[str, Any],
    route_data: dict[str, Any],
    kind: str,
    *,
    mixed: bool,
) -> None:
    """Zones use named selections; mixed routes ask only for the manual endpoint."""
    for endpoint, zone_id in (("start", "zone.home"), ("end", "zone.work")):
        hass.states.async_set(
            zone_id,
            "0",
            {
                **route_data[endpoint],
                "friendly_name": "Home" if endpoint == "start" else "Work",
            },
        )
    entry = MockConfigEntry(domain=DOMAIN, unique_id="public_service", data={})
    with patch("custom_components.vegvesen.async_setup_entry", return_value=True):
        if kind == "parent":
            manager = hass.config_entries.flow
            result = await manager.async_init(DOMAIN, context={"source": SOURCE_USER})
            result = await menu_action(manager, result, "route")
        else:
            entry.add_to_hass(hass)
            manager = hass.config_entries.subentries
            result = await manager.async_init(
                (entry.entry_id, "route"), context={"source": SOURCE_USER}
            )
        options = result["data_schema"].schema["start_source"].config["options"]
        assert {"value": "zone.home", "label": "Home (zone.home)"} in options
        data = {
            "name": "Commute",
            "corridor_m": 100,
            "forecast_hours": 1,
            "start_source": "zone.home",
            "end_source": "map" if mixed else "zone.work",
        }
        mock_http.get(routing_url(route_data), payload=routing)
        result = await manager.async_configure(result["flow_id"], data)
        if mixed:
            assert result["step_id"] == "route_locations"
            assert list(result["data_schema"].schema) == ["end"]
            field = next(iter(result["data_schema"].schema))
            assert field.default() == {
                "latitude": hass.config.latitude,
                "longitude": hass.config.longitude,
            }
            result = await manager.async_configure(
                result["flow_id"], {"end": route_data["end"]}
            )
        result = await finish_progress(manager, result)
        assert result["step_id"] == "route_overview"
        result = await menu_action(manager, result, "route_save")
        if kind == "parent":
            entry = result["result"]
        subentry = next(iter(entry.subentries.values()))
        assert subentry.data["start_source"] == "zone.home"
        assert subentry.data["start_zone_name"] == "Home"
        assert subentry.data["start"] == route_data["start"]
        assert subentry.data["end"] == route_data["end"]
    # A moved zone does not silently rewrite a saved route. Explicit recalculation
    # resolves the current point and preserves the logical route identity.
    updated = {**route_data, "start": {"latitude": 63.431, "longitude": 10.396}}
    hass.states.async_set(
        "zone.home", "0", {**updated["start"], "friendly_name": "Home"}
    )
    assert subentry.data["start"] == route_data["start"]
    manager = hass.config_entries.subentries
    result = await manager.async_init(
        (entry.entry_id, "route"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    assert sum(len(calls) for calls in mock_http.requests.values()) == 1
    mock_http.get(routing_url(updated), payload=routing)
    result = await menu_action(manager, result, "route_recalculate")
    result = await menu_action(manager, result, "route_save")
    assert result["reason"] == "reconfigure_successful"
    saved = entry.subentries[subentry.subentry_id]
    assert saved.data["start"] == updated["start"]
    assert saved.unique_id == subentry.unique_id
    result = await manager.async_init(
        (entry.entry_id, "route"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": saved.subentry_id},
    )
    hass.states.async_remove("zone.home")
    result = await menu_action(manager, result, "route_recalculate")
    assert result["step_id"] == "route_settings"
    assert result["errors"] == {"start_source": "zone_unavailable"}
    assert entry.subentries[saved.subentry_id].data == saved.data


@pytest.mark.parametrize(
    "damage", ["deleted", "unavailable", "missing_coordinates", "invalid_coordinates"]
)
async def test_zone_missing_during_selection(hass: HomeAssistant, damage: str) -> None:
    """A disappeared zone is never silently replaced by home coordinates."""
    hass.states.async_set("zone.home", "0", {"latitude": 63.43, "longitude": 10.395})
    entry = MockConfigEntry(domain=DOMAIN, unique_id="public_service", data={})
    entry.add_to_hass(hass)
    manager = hass.config_entries.subentries
    result = await manager.async_init(
        (entry.entry_id, "route"), context={"source": SOURCE_USER}
    )
    if damage == "deleted":
        hass.states.async_remove("zone.home")
    else:
        hass.states.async_set(
            "zone.home",
            "unavailable" if damage == "unavailable" else "0",
            {"latitude": "invalid", "longitude": 0}
            if damage == "invalid_coordinates"
            else {},
        )
    result = await manager.async_configure(
        result["flow_id"],
        {
            "name": "Example",
            "start_source": "zone.home",
            "end_source": "map",
            "corridor_m": 100,
            "forecast_hours": 1,
        },
    )
    result = await manager.async_configure(
        result["flow_id"], {"end": {"latitude": 63.305, "longitude": 9.846}}
    )
    result = await finish_progress(manager, result)
    assert result["step_id"] == "route_settings"
    assert result["errors"] == {"start_source": "zone_unavailable"}
    assert not entry.subentries


@pytest.mark.parametrize("language", ["en", "nb"])
@pytest.mark.parametrize("category", ["config", "config_subentries"])
async def test_route_labels(hass: HomeAssistant, language: str, category: str) -> None:
    """All route actions and fields exist in HA's actual translation resources."""
    labels = await async_get_translations(hass, language, category, {DOMAIN})
    prefix = f"component.{DOMAIN}.{category}"
    if category == "config_subentries":
        prefix += ".route"
        assert labels[f"{prefix}.initiate_flow.user"] == (
            "Legg til rute" if language == "nb" else "Add route"
        )
        assert labels[f"{prefix}.initiate_flow.reconfigure"]
        assert labels[f"{prefix}.entry_type"]
    for step, fields in {
        "route_settings": [
            "name",
            "start_source",
            "end_source",
            "corridor_m",
            "forecast_hours",
        ],
        "route_locations": ["start", "end"],
        "route_choice": ["route"],
    }.items():
        for field in fields:
            assert labels[f"{prefix}.step.{step}.data.{field}"]
    for action in ("route_settings", "route_choice", "route_recalculate", "route_save"):
        assert labels[f"{prefix}.step.route_overview.menu_options.{action}"]
    assert labels[f"{prefix}.error.off_road_network"] == (
        "Velg et punkt nærmere en vei som støttes av rutetjenesten."
        if language == "nb"
        else "Choose a point closer to a road supported by the routing service."
    )
    selectors = await async_get_translations(hass, language, "selector", {DOMAIN})
    assert selectors[f"component.{DOMAIN}.selector.route_endpoint.options.map"] == (
        "Velg på kart" if language == "nb" else "Choose on map"
    )

    entities = await async_get_translations(hass, language, "entity", {DOMAIN})
    for key in (
        "road_condition",
        "slip_risk",
        "minimum_road_temperature",
        "maximum_road_temperature",
        "forecast_time",
        "forecast_segments",
    ):
        assert entities[f"component.{DOMAIN}.entity.sensor.route_{key}.name"]
