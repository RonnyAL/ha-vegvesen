"""Dashboard access resolves stable route identities without new network I/O."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vegvesen.const import DOMAIN
from custom_components.vegvesen.route_geometry import make_corridor

from .helpers import page
from .test_routes import forecast_url


async def test_route_card_snapshot_lifecycle(
    hass: Any,
    hass_ws_client: Any,
    mock_http: Any,
    route_data: dict,
    forecasts: list,
) -> None:
    """Read exact cached values, follow a renamed entity, fail closed and recover."""
    target = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(
        hours=1
    )
    for forecast in forecasts:
        forecast["properties"]["FORECAST_TIME"] = target.isoformat()
    # Zero and an unusual temperature must survive transport unchanged.
    forecasts[0]["properties"]["ROAD_TEMPERATURE"] = -999.0
    forecasts[1]["properties"]["ROAD_TEMPERATURE"] = 0
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="public_service",
        subentries_data=[
            {
                "subentry_type": "route",
                "title": "Public route",
                "data": route_data,
                "unique_id": "route:example-route",
            }
        ],
    )
    entry.add_to_hass(hass)
    url = forecast_url(make_corridor(route_data["geometry"], 100).bbox, target)
    mock_http.get(url, payload=page(forecasts))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("image", DOMAIN, "route:example-route:map")
    registry.async_update_entity(entity_id, new_entity_id="image.renamed_route")
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)

    async def request(entity_id: str = "image.renamed_route") -> dict:
        await client.send_json_auto_id(
            {"type": "vegvesen/route_map", "entity_id": entity_id}
        )
        return await client.receive_json()

    result = await request()
    assert result["success"]
    data = result["result"]
    assert data["geometry"] == route_data["geometry"]
    coordinator = next(iter(entry.runtime_data.routes.values()))
    assert data["segments"] == [
        {
            "type": "Feature",
            "id": record.source_id,
            "geometry": record.geometry,
            "properties": record.properties,
        }
        for record in coordinator.data.segments
    ]
    assert {
        record["properties"]["ROAD_TEMPERATURE"] for record in data["segments"]
    } >= {-999.0, 0}
    assert sum(len(calls) for calls in mock_http.requests.values()) == 1
    assert (await request("image.nonexistent"))["error"]["code"] == "invalid_route"
    sensor = registry.async_get_entity_id(
        "sensor", DOMAIN, "route:example-route:road_condition"
    )
    assert (await request(sensor))["error"]["code"] == "invalid_route"
    mock_http.get(url, status=503)
    await coordinator.async_refresh()
    assert (await request())["error"]["code"] == "unavailable"
    mock_http.get(url, payload=page([]))
    await coordinator.async_refresh()
    assert (await request())["result"]["segments"] == []
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert (await request())["error"]["code"] == "unavailable"


async def test_route_card_access_and_resource(
    hass: Any, hass_ws_client: Any, hass_client_no_auth: Any
) -> None:
    """Public JS contains no private map data; authenticated reads honor HA policy."""
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)
    with patch(
        "homeassistant.auth.permissions.PolicyPermissions.check_entity",
        return_value=False,
    ):
        await client.send_json(
            {"id": 1, "type": "vegvesen/route_map", "entity_id": "image.route"}
        )
        assert (await client.receive_json())["error"]["code"] == "unauthorized"
    http = await hass_client_no_auth()
    for filename in ("vegvesen-route-map.js", "maplibre-gl-worker.js"):
        response = await http.get(f"/vegvesen/route-map/{filename}")
        assert response.status == 200
        assert "javascript" in response.content_type
