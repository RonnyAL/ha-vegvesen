"""API-reported endpoint constraints and variable forecast availability."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vegvesen.const import DOMAIN
from custom_components.vegvesen.route_api import RouteApiClient

from .helpers import finish_progress, menu_action, page
from .test_routes import forecast_url, routing_url

if TYPE_CHECKING:
    from aioresponses import aioresponses
    from homeassistant.core import HomeAssistant


@pytest.mark.parametrize("kind", ["parent", "subentry"])
@pytest.mark.parametrize("endpoint", ["start", "end"])
@pytest.mark.parametrize("mode", ["map", "zone"])
async def test_off_network_endpoint_can_be_corrected(
    hass: HomeAssistant,
    mock_http: aioresponses,
    route_data: dict[str, Any],
    routing: dict[str, Any],
    kind: str,
    endpoint: str,
    mode: str,
) -> None:
    """Return to the offending map/zone field, retain the draft, and allow retry."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="public_service", data={})
    if mode == "zone":
        hass.states.async_set(f"zone.{endpoint}", "0", route_data[endpoint])
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
    settings = {
        **{key: route_data[key] for key in ("name", "corridor_m", "forecast_hours")},
        "start_source": "map",
        "end_source": "map",
    }
    if mode == "zone":
        settings[f"{endpoint}_source"] = f"zone.{endpoint}"
    result = await manager.async_configure(result["flow_id"], settings)
    points = {
        key: route_data[key]
        for key in ("start", "end")
        if settings[f"{key}_source"] == "map"
    }
    mock_http.get(
        routing_url(route_data),
        status=404,
        payload={"code": 9200 if endpoint == "start" else 9201},
    )
    result = await manager.async_configure(result["flow_id"], points)
    result = await finish_progress(manager, result)
    field = endpoint if mode == "map" else f"{endpoint}_source"
    assert result["step_id"] == (
        "route_locations" if mode == "map" else "route_settings"
    )
    assert result["errors"] == {field: "off_road_network"}
    assert not entry.subentries
    defaults = {str(key): key.default() for key in result["data_schema"].schema}
    assert defaults[field] == (
        route_data[endpoint] if mode == "map" else f"zone.{endpoint}"
    )
    corrected = {
        **route_data,
        endpoint: {
            **route_data[endpoint],
            "longitude": route_data[endpoint]["longitude"] + 0.01,
        },
    }
    mock_http.get(routing_url(corrected), payload=routing)
    if mode == "zone":
        hass.states.async_set(f"zone.{endpoint}", "0", corrected[endpoint])
        result = await manager.async_configure(result["flow_id"], settings)
    else:
        points[endpoint] = corrected[endpoint]
    result = await manager.async_configure(result["flow_id"], points)
    result = await finish_progress(manager, result)
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "route_overview"
    assert result["description_placeholders"]["name"] == route_data["name"]
    assert not entry.subentries
    manager.async_abort(result["flow_id"])


async def test_unpublished_forecast_is_empty_without_fallback(
    hass: HomeAssistant, mock_http: aioresponses
) -> None:
    """A valid but unpublished target is not an API error or a nearer forecast."""
    target = datetime(2026, 10, 5, 10, tzinfo=UTC)
    bbox = "9.8,63.3,10.4,63.5"
    mock_http.get(forecast_url(bbox, target), payload=page([]))
    client = RouteApiClient(async_get_clientsession(hass))
    assert await client.async_forecasts(bbox, target) == {}
    assert sum(map(len, mock_http.requests.values())) == 1
