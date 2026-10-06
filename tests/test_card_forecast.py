"""Requested-hour map transport shares the action cache and read restrictions."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from aioresponses import CallbackResult
from homeassistant.auth.permissions import PolicyPermissions
from homeassistant.helpers import entity_registry as er

from .helpers import page
from .test_forecast_action import action_route as action_route  # noqa: PLC0414
from .test_forecast_action import respond
from .test_route_polling import request_count
from .test_routes import source_entity


@pytest.fixture(autouse=True)
def _forecast_clock(freezer: Any) -> None:
    """Freeze before HA issues the websocket client's authentication token."""
    freezer.move_to("2026-10-06T06:15:00+00:00")


@pytest.mark.parametrize("legacy", [False, True])
async def test_requested_map_and_action_share_cache(
    hass: Any, hass_ws_client: Any, mock_http: Any, action_route: dict, *, legacy: bool
) -> None:
    """The map gets source IDs/geometry while normal sensors and polling stay intact."""
    client = await hass_ws_client(hass)
    target = respond(mock_http, action_route, 2)
    before = action_route["coordinator"].data
    states = hass.states.async_all()
    selection = (
        {"entity_id": source_entity(hass, "slip_risk")}
        if legacy
        else {"device_id": action_route["device_id"]}
    )
    await client.send_json_auto_id(
        {
            "type": "vegvesen/route_map",
            **selection,
            "forecast_time": target.isoformat(),
        }
    )
    response = await client.receive_json()
    assert response["success"]
    data = response["result"]
    assert data["forecast_time"] == target.isoformat()
    assert data["geometry"] == action_route["coordinator"].subentry.data["geometry"]
    assert len(data["segments"]) == 3
    assert len({segment["id"] for segment in data["segments"]}) == 3
    action = await action_route["call"](forecast_time=target.isoformat())
    assert [s["properties"] for s in data["segments"]] == [
        s["properties"] for s in action["segments"]
    ]
    assert request_count(mock_http) == 2
    assert action_route["coordinator"].data is before
    assert hass.states.async_all() == states
    await client.send_json_auto_id({"type": "vegvesen/route_map", **selection})
    assert (await client.receive_json())["result"][
        "forecast_time"
    ] == before.forecast_time.isoformat()
    assert request_count(mock_http) == 2


@pytest.mark.parametrize("failure", ["page", "wrong_hour", "rate_limit", "time"])
async def test_requested_map_errors(
    hass: Any, hass_ws_client: Any, mock_http: Any, action_route: dict, failure: str
) -> None:
    """Never turn a failed or incomplete query into a successful map snapshot."""
    client = await hass_ws_client(hass)
    target = action_route["now"] + timedelta(hours=2)
    if failure == "time":
        target += timedelta(days=1)
        code = "forecast_time_out_of_range"
    elif failure == "rate_limit":
        respond(mock_http, action_route, 2, status=429, headers={"Retry-After": "120"})
        code = "forecast_rate_limited"
    else:
        payload = page(
            action_route["records"](
                action_route["now"] if failure == "wrong_hour" else target
            )
        )
        if failure == "page":
            payload["numberMatched"] = 4  # Three records with no final page.
        respond(mock_http, action_route, 2, payload=payload)
        code = "forecast_request_failed"
    await client.send_json_auto_id(
        {
            "type": "vegvesen/route_map",
            "device_id": action_route["device_id"],
            "forecast_time": target.isoformat(),
        }
    )
    assert (await client.receive_json())["error"]["code"] == code
    assert action_route["coordinator"].last_update_success
    assert request_count(mock_http) == (1 if failure == "time" else 2)


async def test_empty_hour_and_independent_recovery(
    hass: Any, hass_ws_client: Any, mock_http: Any, action_route: dict
) -> None:
    """A healthy requested hour remains queryable when the sensor hour failed."""
    respond(mock_http, action_route, 0, status=503)
    await action_route["coordinator"].async_refresh()
    assert not action_route["coordinator"].last_update_success
    client = await hass_ws_client(hass)
    target = respond(mock_http, action_route, 24, payload=page([]))
    await client.send_json_auto_id(
        {
            "type": "vegvesen/route_map",
            "device_id": action_route["device_id"],
            "forecast_time": target.isoformat(),
        }
    )
    response = await client.receive_json()
    assert response["success"]
    assert response["result"]["segments"] == []
    assert not action_route["coordinator"].last_update_success


@pytest.mark.parametrize("change", ["permissions", "unload", "subentry"])
async def test_access_rechecked_after_io(
    hass: Any, hass_ws_client: Any, mock_http: Any, action_route: dict, change: str
) -> None:
    """An in-flight result cannot outlive its route or authorization."""
    client = await hass_ws_client(hass)
    entered, release = asyncio.Event(), asyncio.Event()
    target = action_route["now"] + timedelta(hours=2)

    async def held(*_args: Any, **_kwargs: Any) -> CallbackResult:
        entered.set()
        await release.wait()
        return CallbackResult(payload=page(action_route["records"](target)))

    respond(mock_http, action_route, 2, callback=held)
    await client.send_json_auto_id(
        {
            "type": "vegvesen/route_map",
            "device_id": action_route["device_id"],
            "forecast_time": target.isoformat(),
        }
    )
    await asyncio.wait_for(entered.wait(), 2)
    entry = action_route["entry"]
    if change == "unload":
        assert await hass.config_entries.async_unload(entry.entry_id)
    elif change == "subentry":
        subentry = next(iter(entry.subentries.values()))
        hass.config_entries.async_update_subentry(
            entry, subentry, data={**subentry.data, "corridor_m": 10}
        )
    with patch.object(
        PolicyPermissions, "check_entity", return_value=change != "permissions"
    ):
        release.set()
        response = await asyncio.wait_for(client.receive_json(), 2)
    assert response["error"]["code"] == (
        "unauthorized" if change == "permissions" else "unavailable"
    )


async def test_denied_request_never_reaches_source(
    hass: Any, hass_ws_client: Any, mock_http: Any, action_route: dict
) -> None:
    """Device-based map reads retain HA's entity permission checks."""
    client = await hass_ws_client(hass)
    device = er.async_get(hass).async_get(source_entity(hass, "slip_risk")).device_id
    with patch.object(PolicyPermissions, "check_entity", return_value=False):
        await client.send_json_auto_id(
            {
                "type": "vegvesen/route_map",
                "device_id": device,
                "forecast_time": (action_route["now"] + timedelta(hours=2)).isoformat(),
            }
        )
        assert (await client.receive_json())["error"]["code"] == "unauthorized"
    assert request_count(mock_http) == 1
