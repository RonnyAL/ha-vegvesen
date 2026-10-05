"""Automatic route discovery, independent failures and on-demand image lifecycle."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import replace
from time import monotonic
from typing import Any
from unittest.mock import patch

import pytest
from aioresponses import CallbackResult
from homeassistant.helpers import entity_registry as er

from custom_components.vegvesen.api import (
    VegvesenApiError,
    parse_camera,
    parse_station,
)
from custom_components.vegvesen.coordinator import CameraSnapshot
from custom_components.vegvesen.discovery import async_get_discovery
from custom_components.vegvesen.route_sources import matching_sources

from .helpers import camera_url, page, weather_url
from .test_route_card import card_route as card_route  # noqa: PLC0414
from .test_route_card import frontend_urls as frontend_urls  # noqa: PLC0414


@pytest.fixture
def map_sources(features: list, camera_features: list, route_data: dict) -> tuple:
    """Move public records onto the public route for deterministic proximity tests."""
    geometry = route_data["geometry"]
    point = geometry["coordinates"][0]
    if geometry["type"] == "MultiLineString":
        point = point[0]
    for feature in [*features, *camera_features]:
        feature["geometry"] = {"type": "Point", "coordinates": point}
    for feature, value in zip(features, [0, None, -999], strict=True):
        feature["properties"]["AIR_TEMPERATURE"] = value
    camera_features[1]["geometry"]["coordinates"] = [0, 0]
    return features, camera_features


async def ready(client: Any, *, camera_status: str = "ready") -> dict:
    """Drain loading events until both independent catalogues have completed."""
    for _ in range(20):
        event = (await client.receive_json())["event"]
        data = event.get("data", {})
        if (
            data.get("weather", {}).get("status") == "ready"
            and data.get("cameras", {}).get("status") == camera_status
        ):
            return data
    pytest.fail("No complete source event")


async def subscribe(client: Any, **options: Any) -> None:
    """Subscribe through HA's real authenticated socket API."""
    await client.send_json(
        {
            "id": 1,
            "type": "vegvesen/subscribe_route_sources",
            "entity_id": "sensor.renamed_route",
            "show_cameras": True,
            "show_weather": True,
            **options,
        }
    )
    assert (await client.receive_json())["success"]


async def test_discovery_shared_atomic_and_independent(
    hass: Any,
    hass_ws_client: Any,
    mock_http: Any,
    card_route: tuple,
    map_sources: tuple,
    route_data: dict,
) -> None:
    """No manual sources, extra entities or images; failures clear just their layer."""
    entry, forecast, forecast_url = card_route
    weather, cameras = map_sources
    before = set(er.async_get(hass).entities)
    mock_http.get(weather_url(), payload=page(weather))
    mock_http.get(camera_url(), payload=page(cameras))
    client = await hass_ws_client(hass)
    await subscribe(client)
    result = await ready(client)
    assert {item["air_temperature"] for item in result["weather"]["items"]} == {
        0,
        None,
        -999,
    }
    assert len(result["cameras"]["items"]) == 2
    assert result["geometry"] == route_data["geometry"]
    assert "image_url" not in str(result)
    assert set(er.async_get(hass).entities) == before
    assert len(entry.subentries) == 1
    assert sum(map(len, mock_http.requests.values())) == 3  # Forecast + two catalogues.

    second = await hass_ws_client(hass)
    await subscribe(second)
    await ready(second)
    assert sum(map(len, mock_http.requests.values())) == 3
    await second.close()
    await hass.async_block_till_done(wait_background_tasks=True)

    # Forecast failure cannot hide the saved route or healthy source layers.
    mock_http.get(forecast_url, status=503)
    await forecast.async_refresh()
    assert (await ready(client))["geometry"] == result["geometry"]

    coordinator = entry.runtime_data.sources["cameras"]
    coordinator.cache._expires = 0
    next_url = camera_url(start_index=1)
    mock_http.get(camera_url(), payload=page(cameras[:1], matched=3, next_url=next_url))
    mock_http.get(next_url, status=503)
    await coordinator.async_refresh()
    failed = await ready(client, camera_status="unavailable")
    assert failed["cameras"]["items"] == []
    assert failed["weather"] == result["weather"]
    mock_http.get(camera_url(), payload=page([]))
    await coordinator.async_refresh()
    assert (await ready(client))["cameras"]["items"] == []
    # Empty successful catalogues are cached, too.
    requests = sum(map(len, mock_http.requests.values()))
    await coordinator.async_refresh()
    assert sum(map(len, mock_http.requests.values())) == requests
    await client.close()
    await hass.async_block_till_done(wait_background_tasks=True)
    for source in entry.runtime_data.sources.values():
        assert not source._listeners
        assert source._unsub_refresh is None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_source_subscription_reload_permissions_and_off(
    hass: Any,
    hass_ws_client: Any,
    mock_http: Any,
    card_route: tuple,
    map_sources: tuple,
    forecasts: list,
) -> None:
    """Rebind after reload; stop polling on revoked access or disconnect."""
    entry, _forecast, url = card_route
    weather, cameras = map_sources
    client = await hass_ws_client(hass)
    await subscribe(client, show_cameras=False, show_weather=False)
    assert (await client.receive_json())["event"]["data"].keys() == {"geometry"}
    assert sum(map(len, mock_http.requests.values())) == 1
    await client.close()

    mock_http.get(weather_url(), payload=page(weather))
    mock_http.get(camera_url(), payload=page(cameras))
    client = await hass_ws_client(hass)
    await subscribe(client)
    await ready(client)
    old = entry.runtime_data.sources
    with patch(
        "homeassistant.auth.permissions.PolicyPermissions.check_entity",
        return_value=False,
    ):
        er.async_get(hass).async_update_entity(
            "sensor.renamed_route", new_entity_id="sensor.renamed_again"
        )
        assert (await client.receive_json())["event"] == {"error": "unauthorized"}
        assert all(not source._listeners for source in old.values())
    er.async_get(hass).async_update_entity(
        "sensor.renamed_again", new_entity_id="sensor.renamed_route"
    )
    await ready(client)
    mock_http.get(url, payload=page(forecasts))
    assert await hass.config_entries.async_reload(entry.entry_id)
    await ready(client)
    assert all(not source._listeners for source in old.values())
    assert all(source._listeners for source in entry.runtime_data.sources.values())
    assert sum(map(len, mock_http.requests.values())) == 4
    await client.close()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_camera_on_demand_cache_and_failures(
    hass: Any,
    hass_ws_client: Any,
    mock_http: Any,
    card_route: tuple,
    map_sources: tuple,
    jpeg: bytes,
) -> None:
    """Share images, statuses and failed attempts without camera entities."""
    entry, _forecast, _url = card_route
    weather, cameras = map_sources
    mock_http.get(weather_url(), payload=page(weather))
    mock_http.get(camera_url(), payload=page(cameras))
    subscriber = await hass_ws_client(hass)
    await subscribe(subscriber)
    await ready(subscriber)
    client = await hass_ws_client(hass)
    source_id = cameras[0]["properties"]["CAMERA_ID"]
    image_url = cameras[0]["properties"]["STILL_IMAGE_URL"]
    mock_http.get(camera_url((source_id,)), payload=page(cameras[:1]))
    mock_http.get(image_url, body=jpeg, content_type="image/jpeg")

    async def request(selected: str = source_id) -> dict:
        await client.send_json_auto_id(
            {
                "type": "vegvesen/route_camera",
                "entity_id": "sensor.renamed_route",
                "source_id": selected,
            }
        )
        return await client.receive_json()

    first = (await request())["result"]
    assert base64.b64decode(first["content"]) == jpeg
    assert first["camera"]["source_id"] == source_id
    assert (await request())["result"] == first
    assert sum(map(len, mock_http.requests.values())) == 5
    far_id = cameras[1]["properties"]["CAMERA_ID"]
    assert (await request(far_id))["error"]["code"] == "invalid_source"
    assert (await request("unknown"))["error"]["code"] == "unavailable"

    # A failed image replaces old bytes. Its metadata remains meaningful.
    entry.runtime_data.camera_frames._frames.clear()
    mock_http.get(camera_url((source_id,)), payload=page(cameras[:1]))
    mock_http.get(image_url, status=503)
    failed = (await request())["result"]
    assert failed["content"] is None
    assert failed["camera"]["availability"] == "videoOrImagesAvailable"
    assert (await request())["result"] == failed
    requests = sum(map(len, mock_http.requests.values()))
    assert requests == 7

    entry.runtime_data.camera_frames._frames.clear()
    mock_http.get(camera_url((source_id,)), status=503)
    assert (await request())["result"]["camera"] is None
    assert sum(map(len, mock_http.requests.values())) == requests + 1
    entry.runtime_data.camera_frames._frames.clear()
    mock_http.get(camera_url((source_id,)), payload=page(cameras[:1]))
    mock_http.get(image_url, body=jpeg, content_type="image/jpeg")
    assert (await request())["result"] == first
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert (await request())["error"]["code"] == "unavailable"
    await subscriber.close()


async def test_frame_coalescing_and_bounded_transport(
    hass: Any,
    mock_http: Any,
    card_route: tuple,
    camera_features: list,
    jpeg: bytes,
) -> None:
    """Concurrent viewers fetch once; oversized responses cannot fill an image cache."""
    entry, _, _ = card_route
    source_id = camera_features[0]["properties"]["CAMERA_ID"]
    image_url = camera_features[0]["properties"]["STILL_IMAGE_URL"]
    mock_http.get(camera_url((source_id,)), payload=page(camera_features[:1]))
    mock_http.get(image_url, body=jpeg, content_type="image/jpeg")
    frames = entry.runtime_data.camera_frames
    started, release = asyncio.Event(), asyncio.Event()
    original = frames.client.async_get_image

    async def pending(url: str) -> bytes:
        started.set()
        await release.wait()
        return await original(url)

    with patch.object(frames.client, "async_get_image", side_effect=pending):
        waiting = asyncio.gather(*(frames.async_get(source_id) for _ in range(4)))
        await started.wait()
        assert frames._locks[source_id][1] == 4
        release.set()
        result = await waiting
    assert all(frame.image == jpeg for frame in result)
    assert sum(map(len, mock_http.requests.values())) == 3
    assert not frames._locks
    mock_http.get(
        image_url,
        body=b"\xff\xd8\xff" + b"x" * 1024,
        content_type="image/jpeg",
    )
    with (
        patch("custom_components.vegvesen.api.MAX_IMAGE_BYTES", 512),
        pytest.raises(VegvesenApiError, match="size limit"),
    ):
        await entry.runtime_data.client.async_get_image(image_url)
    assert await hass.config_entries.async_unload(entry.entry_id)


def test_source_proximity_and_missing_coordinates(features: list) -> None:
    """Match disconnected parts without bridging or changing source values."""
    station = parse_station(features[0])
    sources = {
        name: replace(station, source_id=name, latitude=lat, longitude=lng)
        for name, lat, lng in [
            ("on", 60, 10.005),
            ("near", 60.001, 10.005),
            ("far", 60.01, 10.005),
            ("gap", 60, 10.5),
            ("second", 60, 11.005),
            ("missing", None, 10),
            ("invalid", float("nan"), 10),
        ]
    }
    geometry = {
        "type": "MultiLineString",
        "coordinates": [
            [[10, 60], [10.01, 60]],
            [[11, 60], [11.01, 60]],
        ],
    }
    assert {s.source_id for s in matching_sources(geometry, 10, sources)} == {
        "on",
        "second",
    }
    assert {s.source_id for s in matching_sources(geometry, 250, sources)} == {
        "on",
        "near",
        "second",
    }


async def test_manual_camera_cache_and_access_after_io(
    hass: Any,
    hass_ws_client: Any,
    mock_http: Any,
    card_route: tuple,
    map_sources: tuple,
    jpeg: bytes,
) -> None:
    """Reuse configured bytes and reject pending frames after route unloading."""
    entry, _, _ = card_route
    _, cameras = map_sources
    camera = parse_camera(cameras[0])
    mock_http.get(camera_url(), payload=page(cameras))
    await entry.runtime_data.sources["cameras"].async_refresh()
    manual = entry.runtime_data.cameras
    manual.camera_ids = frozenset({camera.source_id})
    manual.data = {camera.source_id: CameraSnapshot(camera, jpeg)}
    manual.refreshed_at = monotonic()
    client = await hass_ws_client(hass)
    message = {
        "type": "vegvesen/route_camera",
        "entity_id": "sensor.renamed_route",
        "source_id": camera.source_id,
    }
    await client.send_json_auto_id(message)
    assert base64.b64decode((await client.receive_json())["result"]["content"]) == jpeg
    assert sum(map(len, mock_http.requests.values())) == 2
    manual.last_update_success = False
    await client.send_json_auto_id(message)
    assert (await client.receive_json())["result"]["content"] is None
    assert sum(map(len, mock_http.requests.values())) == 2

    manual.refreshed_at = 0  # Disabled manual entities must not freeze map images.
    started, release = asyncio.Event(), asyncio.Event()

    async def pending(*_: Any, **__: Any) -> CallbackResult:
        started.set()
        await release.wait()
        return CallbackResult(body=jpeg, content_type="image/jpeg")

    mock_http.get(camera_url((camera.source_id,)), payload=page(cameras[:1]))
    mock_http.get(camera.image_url, callback=pending)
    await client.send_json_auto_id(message)
    await started.wait()
    assert await hass.config_entries.async_unload(entry.entry_id)
    release.set()
    assert (await client.receive_json())["error"]["code"] == "unavailable"


@pytest.mark.parametrize("distance", [0, 2001, True, 2.5, "250"])
async def test_invalid_discovery_distance(
    hass: Any,
    hass_ws_client: Any,
    card_route: tuple,
    distance: Any,
) -> None:
    """Reject invalid settings before making any discovery requests."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "vegvesen/subscribe_route_sources",
            "entity_id": "sensor.renamed_route",
            "show_cameras": True,
            "camera_distance_m": distance,
        }
    )
    assert (await client.receive_json())["error"]["code"] == "invalid_format"
    assert await hass.config_entries.async_unload(card_route[0].entry_id)


async def test_weather_only_and_rate_limit(
    hass: Any,
    hass_ws_client: Any,
    mock_http: Any,
    card_route: tuple,
) -> None:
    """Poll weather alone; keep server backoff across additional viewers."""
    entry, _, _ = card_route
    mock_http.get(weather_url(), status=429, headers={"Retry-After": "1800"})
    client = await hass_ws_client(hass)
    await subscribe(client, show_cameras=False)
    for _ in range(5):
        data = (await client.receive_json())["event"]["data"]
        if data["weather"]["status"] == "unavailable":
            break
    assert data == {
        "geometry": data["geometry"],
        "weather": {"status": "unavailable", "items": []},
    }
    source = entry.runtime_data.sources["weather"]
    await source.async_refresh()
    assert not source.last_update_success
    assert sum(map(len, mock_http.requests.values())) == 2
    assert not entry.runtime_data.sources["cameras"]._listeners
    await client.close()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_catalogue_poll_jitter(hass: Any, mock_http: Any, features: list) -> None:
    """A slightly early poll cannot defer new observations a full interval."""
    cache = async_get_discovery(hass).weather
    mock_http.get(weather_url(), payload=page(features))
    mock_http.get(weather_url(), payload=page([]))
    with patch("custom_components.vegvesen.discovery.monotonic", return_value=10):
        assert await cache.async_get()
    with patch("custom_components.vegvesen.discovery.monotonic", return_value=609.2):
        assert await cache.async_get() == {}
