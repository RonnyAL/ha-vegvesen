"""Cached map transport, stable identity, subscription cleanup and access control."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vegvesen.const import DOMAIN
from custom_components.vegvesen.route_geometry import make_corridor

from .helpers import page
from .test_routes import forecast_url


@pytest.fixture
async def card_route(
    hass: Any, mock_http: Any, route_data: dict, forecasts: list
) -> tuple:
    """Load a public fixture and simulate upgrading a renamed beta image."""
    target = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(
        hours=1
    )
    for forecast in forecasts:
        forecast["properties"]["FORECAST_TIME"] = target.isoformat()
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
    registry = er.async_get(hass)
    retired = registry.async_get_or_create(
        "image",
        DOMAIN,
        "route:example-route:map",
        config_entry=entry,
        config_subentry_id=next(iter(entry.subentries)),
        suggested_object_id="renamed_old_image",
    )
    url = forecast_url(make_corridor(route_data["geometry"], 100).bbox, target)
    mock_http.get(url, payload=page(forecasts))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(retired.entity_id) is None
    assert not hass.states.async_all("image")
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, "route:example-route:highest_slip_risk"
    )
    registry.async_update_entity(entity_id, new_entity_id="sensor.renamed_route")
    await hass.async_block_till_done()
    return entry, next(iter(entry.runtime_data.routes.values())), url


@pytest.mark.parametrize("use_device", [False, True])
async def test_route_card_snapshot_lifecycle(
    hass: Any,
    hass_ws_client: Any,
    mock_http: Any,
    card_route: tuple,
    route_data: dict,
    *,
    use_device: bool,
) -> None:
    """A renamed sensor identifies the route; unknown summary still has map data."""
    entry, coordinator, url = card_route
    client = await hass_ws_client(hass)
    device_id = er.async_get(hass).async_get("sensor.renamed_route").device_id

    async def request(entity_id: str = "sensor.renamed_route") -> dict:
        await client.send_json_auto_id(
            {
                "type": "vegvesen/route_map",
                **(
                    {
                        "device_id": device_id
                        if entity_id == "sensor.renamed_route"
                        else "missing"
                    }
                    if use_device
                    else {"entity_id": entity_id}
                ),
            }
        )
        return await client.receive_json()

    data = (await request())["result"]
    assert data["geometry"] == route_data["geometry"]
    assert {r["properties"]["ROAD_TEMPERATURE"] for r in data["segments"]} >= {
        -999.0,
        0,
    }
    assert sum(map(len, mock_http.requests.values())) == 1
    assert (await request("sensor.nonexistent"))["error"]["code"] == "invalid_route"
    mock_http.get(url, status=503)
    await coordinator.async_refresh()
    assert (await request())["error"]["code"] == "unavailable"
    mock_http.get(url, payload=page([]))
    await coordinator.async_refresh()
    data = (await request())["result"]
    assert data["segments"] == []
    assert data["summary"]["highest_slip_risk"] is None
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert (await request())["error"]["code"] == "unavailable"


@pytest.mark.parametrize("use_device", [False, True])
async def test_route_subscription_lifecycle(
    hass: Any,
    hass_ws_client: Any,
    mock_http: Any,
    card_route: tuple,
    forecasts: list,
    *,
    use_device: bool,
) -> None:
    """Changed segments push even when summary/time/count stay equal; reload rebinds."""
    entry, coordinator, url = card_route
    client = await hass_ws_client(hass)
    listeners = len(coordinator._listeners)
    await client.send_json(
        {
            "id": 1,
            "type": "vegvesen/subscribe_route_map",
            **(
                {
                    "device_id": er.async_get(hass)
                    .async_get("sensor.renamed_route")
                    .device_id
                }
                if use_device
                else {"entity_id": "sensor.renamed_route"}
            ),
        }
    )
    assert (await client.receive_json())["success"]
    initial = (await client.receive_json())["event"]["data"]
    assert len(coordinator._listeners) == listeners + 1
    before = hass.states.get("sensor.renamed_route")
    changed = deepcopy(forecasts)
    changed[0]["properties"]["ROAD_TEMPERATURE"] = -998.0
    mock_http.get(url, payload=page(changed))
    await coordinator.async_refresh()
    update = (await client.receive_json())["event"]["data"]
    assert update["summary"] == initial["summary"]
    assert update["segments"] != initial["segments"]
    assert hass.states.get("sensor.renamed_route").last_updated == before.last_updated
    mock_http.get(url, status=503)
    await coordinator.async_refresh()
    assert (await client.receive_json())["event"] == {"error": "unavailable"}
    mock_http.get(url, payload=page([]))
    await coordinator.async_refresh()
    assert (await client.receive_json())["event"]["data"]["segments"] == []
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not coordinator._listeners
    mock_http.get(url, payload=page(forecasts))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    # State transitions can emit several unavailable events before loaded.
    for _ in range(10):
        event = (await client.receive_json())["event"]
        if "data" in event:
            break
        assert event == {"error": "unavailable"}
    assert event["data"]["segments"]
    replacement = next(iter(entry.runtime_data.routes.values()))
    assert replacement is not coordinator
    assert len(replacement._listeners) == listeners + 1
    await client.send_json({"id": 2, "type": "unsubscribe_events", "subscription": 1})
    assert (await client.receive_json())["success"]
    assert len(replacement._listeners) == listeners
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("use_device", [False, True])
async def test_route_subscription_permission_change_and_disconnect(
    hass: Any, hass_ws_client: Any, card_route: tuple, *, use_device: bool
) -> None:
    """Recheck entity permission on updates/rename and detach on socket close."""
    entry, coordinator, _url = card_route
    client = await hass_ws_client(hass)
    listeners = len(coordinator._listeners)
    await client.send_json(
        {
            "id": 1,
            "type": "vegvesen/subscribe_route_map",
            **(
                {
                    "device_id": er.async_get(hass)
                    .async_get("sensor.renamed_route")
                    .device_id
                }
                if use_device
                else {"entity_id": "sensor.renamed_route"}
            ),
        }
    )
    await client.receive_json()
    await client.receive_json()
    with patch(
        "homeassistant.auth.permissions.PolicyPermissions.check_entity",
        return_value=False,
    ):
        er.async_get(hass).async_update_entity(
            "sensor.renamed_route", new_entity_id="sensor.second_name"
        )
        await hass.async_block_till_done()
        assert (await client.receive_json())["event"] == {"error": "unauthorized"}
    assert len(coordinator._listeners) == listeners
    # Rename back restores access through the same subscription.
    er.async_get(hass).async_update_entity(
        "sensor.second_name", new_entity_id="sensor.third_name"
    )
    await hass.async_block_till_done()
    assert (await client.receive_json())["event"]["data"]["segments"]
    await client.close()
    await hass.async_block_till_done()
    assert len(coordinator._listeners) == listeners
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_route_card_access_and_resource(
    hass: Any, hass_ws_client: Any, hass_client_no_auth: Any
) -> None:
    """Public JS contains no private map data; authenticated reads honor HA policy."""
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)
    for i, command in enumerate(
        ["vegvesen/route_map", "vegvesen/subscribe_route_map"], 1
    ):
        with patch(
            "homeassistant.auth.permissions.PolicyPermissions.check_entity",
            return_value=False,
        ):
            await client.send_json(
                {"id": i, "type": command, "entity_id": "sensor.route"}
            )
            assert (await client.receive_json())["error"]["code"] == "unauthorized"
    http = await hass_client_no_auth()
    for filename in ("vegvesen-route-map.js", "maplibre-gl-worker.js"):
        response = await http.get(f"/vegvesen/route-map/{filename}")
        assert response.status == 200
        assert "javascript" in response.content_type


async def test_device_selection_survives_disabled_sensors_and_honors_access(
    hass: Any, hass_ws_client: Any, card_route: tuple
) -> None:
    """No particular sensor must stay enabled; permissions still protect the route."""
    entry, _coordinator, _url = card_route
    registry = er.async_get(hass)
    device_id = registry.async_get("sensor.renamed_route").device_id
    client = await hass_ws_client(hass)

    async def request(**target: Any) -> dict:
        await client.send_json_auto_id({"type": "vegvesen/route_map", **target})
        return await client.receive_json()

    for entity in er.async_entries_for_device(registry, device_id):
        registry.async_update_entity(
            entity.entity_id, disabled_by=er.RegistryEntryDisabler.USER
        )
    await hass.async_block_till_done()
    assert (await request(device_id=device_id))["result"]["segments"]
    assert (await request(entity_id="sensor.renamed_route"))["error"][
        "code"
    ] == "unavailable"
    with patch(
        "homeassistant.auth.permissions.PolicyPermissions.check_entity",
        return_value=False,
    ):
        for command in ("vegvesen/route_map", "vegvesen/subscribe_route_map"):
            await client.send_json_auto_id({"type": command, "device_id": device_id})
            assert (await client.receive_json())["error"]["code"] == "unauthorized"
    # A single readable route sensor suffices, irrespective of its summary grade.
    with patch(
        "homeassistant.auth.permissions.PolicyPermissions.check_entity",
        side_effect=lambda entity_id, _policy: entity_id == "sensor.renamed_route",
    ):
        assert (await request(device_id=device_id))["result"]["segments"]
    for target in ({}, {"device_id": device_id, "entity_id": "sensor.renamed_route"}):
        assert (await request(**target))["error"]["code"] == "invalid_format"
    weather = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "weather:example")},
        name="A weather station",
        model="Route forecast",  # Display metadata cannot grant access.
    )
    assert (await request(device_id=weather.id))["error"]["code"] == "invalid_route"
    dr.async_get(hass).async_update_device(
        device_id, disabled_by=dr.DeviceEntryDisabler.USER
    )
    await hass.async_block_till_done()
    assert (await request(device_id=device_id))["error"]["code"] == "unavailable"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_device_subscription_removal_and_registry_cleanup(
    hass: Any, hass_ws_client: Any, card_route: tuple
) -> None:
    """Rename the route device without reconfiguration; removal clears private data."""
    entry, coordinator, _url = card_route
    device_id = er.async_get(hass).async_get("sensor.renamed_route").device_id
    client = await hass_ws_client(hass)
    before = hass.bus.async_listeners()
    await client.send_json(
        {"id": 1, "type": "vegvesen/subscribe_route_map", "device_id": device_id}
    )
    assert (await client.receive_json())["success"]
    assert (await client.receive_json())["event"]["data"]["segments"]
    dr.async_get(hass).async_update_device(device_id, name_by_user="Renamed route")
    await hass.async_block_till_done()
    assert (await client.receive_json())["event"]["data"]["segments"]
    dr.async_get(hass).async_remove_device(device_id)
    await hass.async_block_till_done()
    event = (await client.receive_json())["event"]
    assert event == {"error": "unavailable"}
    await client.close()
    await hass.async_block_till_done()
    after = hass.bus.async_listeners()
    for event_type in (
        dr.EVENT_DEVICE_REGISTRY_UPDATED,
        er.EVENT_ENTITY_REGISTRY_UPDATED,
    ):
        assert after.get(event_type, 0) <= before.get(event_type, 0)
    assert not coordinator._listeners
    assert await hass.config_entries.async_unload(entry.entry_id)
