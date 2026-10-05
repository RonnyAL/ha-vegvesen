"""Exercise actual camera entities, independent failure/recovery, and unloading."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from aioresponses import CallbackResult
from homeassistant.components.camera import async_get_image
from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.vegvesen.const import (
    CAMERA_UPDATE_INTERVAL,
    CONF_CAMERA_ID,
    DOMAIN,
    SUBENTRY_CAMERA,
)

from .helpers import camera_url, page, weather_url

if TYPE_CHECKING:
    from aioresponses import aioresponses
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


def camera_entity_id(hass: HomeAssistant, camera_id: str) -> str:
    """Locate a source camera independently of its display name."""
    found = er.async_get(hass).async_get_entity_id(
        "camera", DOMAIN, f"camera:{camera_id}"
    )
    assert found is not None
    return found


def mock_camera_poll(
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
    jpeg: bytes,
    *,
    failure: str | None = None,
) -> None:
    """Mock one complete selected-camera poll, including each image outcome."""
    mock_http.get(
        camera_url(("3000047_2", "3000063_1")), payload=page(camera_features[:2])
    )
    for index, feature in enumerate(camera_features[:2]):
        url = feature["properties"]["STILL_IMAGE_URL"]
        if index == 0 and failure is not None:
            mock_http.get(
                url,
                status=429 if failure == "rate" else 503,
                headers={"Retry-After": "180"},
            )
        else:
            mock_http.get(url, body=jpeg, content_type="image/jpeg")


async def setup_cameras(
    hass: HomeAssistant,
    camera_entry: MockConfigEntry,
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
    jpeg: bytes,
) -> None:
    """Set up the actual camera platform with network fixtures."""
    camera_entry.add_to_hass(hass)
    mock_camera_poll(mock_http, camera_features, jpeg)
    assert await hass.config_entries.async_setup(camera_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_camera_cache_identity_and_unload(
    hass: HomeAssistant,
    camera_entry: MockConfigEntry,
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
    jpeg: bytes,
    freezer: Any,
) -> None:
    """Cache original JPEGs, attach devices, and stop timers on unload."""
    await setup_cameras(hass, camera_entry, mock_http, camera_features, jpeg)
    coordinator = camera_entry.runtime_data.cameras
    assert coordinator.update_interval == CAMERA_UPDATE_INTERVAL
    assert camera_entry.runtime_data.weather._unsub_refresh is None
    requests = sum(len(items) for items in mock_http.requests.values())
    for subentry in camera_entry.subentries.values():
        source_id = subentry.data[CONF_CAMERA_ID]
        entity_id = camera_entity_id(hass, source_id)
        registered = er.async_get(hass).async_get(entity_id)
        device = dr.async_get(hass).async_get(registered.device_id)
        assert device.identifiers == {(DOMAIN, f"camera:{source_id}")}
        assert registered.config_subentry_id == subentry.subentry_id
        state = hass.states.get(entity_id)
        assert state.state != STATE_UNAVAILABLE
        assert state.attributes["source_availability"] == "videoOrImagesAvailable"
        feature = next(
            f for f in camera_features if f["properties"]["CAMERA_ID"] == source_id
        )
        longitude, latitude = feature["geometry"]["coordinates"]
        assert state.attributes["latitude"] == latitude
        assert state.attributes["longitude"] == longitude
        assert "capture_time" not in state.attributes
        for _ in range(3):
            assert (await async_get_image(hass, entity_id)).content == jpeg
    assert sum(len(items) for items in mock_http.requests.values()) == requests
    session = async_get_clientsession(hass)
    assert await hass.config_entries.async_unload(camera_entry.entry_id)
    assert coordinator._shutdown_requested
    assert coordinator._listeners == {}
    assert coordinator._unsub_refresh is None
    assert not session.closed
    freezer.tick(timedelta(minutes=5))
    async_fire_time_changed(hass, datetime.now(UTC))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert sum(len(items) for items in mock_http.requests.values()) == requests


@pytest.mark.parametrize("geometry", [None, {"type": "Point", "coordinates": [0, 0]}])
async def test_camera_coordinates_do_not_determine_image_availability(
    hass: HomeAssistant,
    camera_entry: MockConfigEntry,
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
    jpeg: bytes,
    geometry: dict[str, Any] | None,
) -> None:
    """Missing positions stay null; zero coordinates survive without losing images."""
    camera_features[0]["geometry"] = geometry
    await setup_cameras(hass, camera_entry, mock_http, camera_features, jpeg)
    entity_id = camera_entity_id(hass, "3000047_2")
    state = hass.states.get(entity_id)
    assert state.state != STATE_UNAVAILABLE
    assert state.attributes["longitude"] == (0 if geometry else None)
    assert state.attributes["latitude"] == (0 if geometry else None)
    assert (await async_get_image(hass, entity_id)).content == jpeg


async def test_image_failure_isolation_and_recovery(
    hass: HomeAssistant,
    camera_entry: MockConfigEntry,
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
    jpeg: bytes,
) -> None:
    """An image HTTP failure removes only that camera's usable still until recovery."""
    await setup_cameras(hass, camera_entry, mock_http, camera_features, jpeg)
    coordinator = camera_entry.runtime_data.cameras
    mock_camera_poll(mock_http, camera_features, jpeg, failure="http")
    await coordinator.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert coordinator.last_update_success
    assert coordinator.data["3000047_2"].image is None
    assert (
        hass.states.get(camera_entity_id(hass, "3000047_2")).state == STATE_UNAVAILABLE
    )
    assert (
        "latitude"
        not in hass.states.get(camera_entity_id(hass, "3000047_2")).attributes
    )
    assert (
        hass.states.get(camera_entity_id(hass, "3000063_1")).state != STATE_UNAVAILABLE
    )
    mock_camera_poll(mock_http, camera_features, jpeg)
    await coordinator.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert (
        await async_get_image(hass, camera_entity_id(hass, "3000047_2"))
    ).content == jpeg
    assert (
        hass.states.get(camera_entity_id(hass, "3000047_2")).attributes["latitude"]
        == camera_features[0]["geometry"]["coordinates"][1]
    )


async def test_image_backoff_and_polling(
    hass: HomeAssistant,
    camera_entry: MockConfigEntry,
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
    jpeg: bytes,
    freezer: Any,
) -> None:
    """Honor image Retry-After without delaying metadata or another camera's images."""
    await setup_cameras(hass, camera_entry, mock_http, camera_features, jpeg)
    mock_camera_poll(mock_http, camera_features, jpeg, failure="rate")
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass, datetime.now(UTC))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert camera_entry.runtime_data.cameras.data["3000047_2"].image is None
    mock_http.get(
        camera_url(("3000047_2", "3000063_1")), payload=page(camera_features[:2])
    )
    mock_http.get(
        camera_features[1]["properties"]["STILL_IMAGE_URL"],
        body=jpeg,
        content_type="image/jpeg",
    )
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass, datetime.now(UTC))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert camera_entry.runtime_data.cameras.last_update_success
    assert camera_entry.runtime_data.cameras.data["3000047_2"].image is None
    requests = sum(map(len, mock_http.requests.values()))
    mock_http.get(
        camera_url(("3000047_2", "3000063_1")), payload=page(camera_features[:2])
    )
    mock_http.get(
        camera_features[1]["properties"]["STILL_IMAGE_URL"],
        body=jpeg,
        content_type="image/jpeg",
    )
    assert await hass.config_entries.async_reload(camera_entry.entry_id)
    assert sum(map(len, mock_http.requests.values())) == requests + 2
    assert camera_entry.runtime_data.cameras.data["3000047_2"].image is None
    mock_camera_poll(mock_http, camera_features, jpeg)
    freezer.tick(timedelta(seconds=121))
    async_fire_time_changed(hass, datetime.now(UTC))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert camera_entry.runtime_data.cameras.data["3000047_2"].image == jpeg


async def test_source_fault_and_absence(
    hass: HomeAssistant,
    camera_entry: MockConfigEntry,
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
    jpeg: bytes,
) -> None:
    """An absent camera or reported fault is unavailable without image requests."""
    await setup_cameras(hass, camera_entry, mock_http, camera_features, jpeg)
    camera_features[0]["properties"]["STATUS_STILL_IMAGE_AVAILABILITY"] = (
        "videoOrImagesUnavailableDueToCameraFault"
    )
    mock_http.get(
        camera_url(("3000047_2", "3000063_1")), payload=page(camera_features[:1])
    )
    requests = sum(len(items) for items in mock_http.requests.values())
    await camera_entry.runtime_data.cameras.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert camera_entry.runtime_data.cameras.last_update_success
    assert (
        hass.states.get(
            er.async_get(hass).async_get_entity_id(
                "sensor", DOMAIN, "camera:3000047_2:availability"
            )
        ).state
        == "videoOrImagesUnavailableDueToCameraFault"
    )
    for source_id in ("3000047_2", "3000063_1"):
        assert (
            hass.states.get(camera_entity_id(hass, source_id)).state
            == STATE_UNAVAILABLE
        )
    assert sum(len(items) for items in mock_http.requests.values()) == requests + 1


async def test_camera_pagination_failure_retains_old_snapshot(
    hass: HomeAssistant,
    camera_entry: MockConfigEntry,
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
    jpeg: bytes,
) -> None:
    """A failed page cannot publish partial data or fetch images."""
    await setup_cameras(hass, camera_entry, mock_http, camera_features, jpeg)
    coordinator = camera_entry.runtime_data.cameras
    previous = coordinator.data
    ids = ("3000047_2", "3000063_1")
    mock_http.get(
        camera_url(ids),
        payload=page(camera_features[:1], matched=2, next_url=camera_url(ids, 1)),
    )
    mock_http.get(camera_url(ids, 1), status=503)
    requests = sum(len(items) for items in mock_http.requests.values())
    await coordinator.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert coordinator.data is previous
    assert not coordinator.last_update_success
    assert sum(len(items) for items in mock_http.requests.values()) == requests + 2
    assert (
        hass.states.get(camera_entity_id(hass, "3000047_2")).state == STATE_UNAVAILABLE
    )
    with pytest.raises(HomeAssistantError):
        await async_get_image(hass, camera_entity_id(hass, "3000047_2"))
    mock_camera_poll(mock_http, camera_features, jpeg)
    await coordinator.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert coordinator.last_update_success


@pytest.mark.parametrize("failed_family", ["weather", "camera"])
async def test_mixed_initial_failure_and_recovery(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    camera_features: list[dict[str, Any]],
    jpeg: bytes,
    failed_family: str,
) -> None:
    """Load the healthy family, then independently recover the failed one."""
    config_entry.add_to_hass(hass)
    for feature in camera_features[:2]:
        source_id = feature["properties"]["CAMERA_ID"]
        hass.config_entries.async_add_subentry(
            config_entry,
            ConfigSubentry(
                subentry_type=SUBENTRY_CAMERA,
                title=feature["properties"]["DESCRIPTION"],
                unique_id=f"camera:{source_id}",
                data={CONF_CAMERA_ID: source_id},
            ),
        )
    if failed_family == "weather":
        mock_http.get(weather_url(("1629006", "1629013")), status=503)
        mock_camera_poll(mock_http, camera_features, jpeg)
    else:
        mock_http.get(weather_url(("1629006", "1629013")), payload=page(features[:2]))
        mock_http.get(camera_url(("3000047_2", "3000063_1")), status=503)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert config_entry.state is ConfigEntryState.LOADED
    temperature = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, "weather_station:1629006:air_temperature"
    )
    assert (hass.states.get(temperature).state == STATE_UNAVAILABLE) == (
        failed_family == "weather"
    )
    assert (
        hass.states.get(camera_entity_id(hass, "3000047_2")).state == STATE_UNAVAILABLE
    ) == (failed_family == "camera")
    if failed_family == "weather":
        mock_http.get(weather_url(("1629006", "1629013")), payload=page(features[:2]))
        await config_entry.runtime_data.weather.async_refresh()
    else:
        mock_camera_poll(mock_http, camera_features, jpeg)
        await config_entry.runtime_data.cameras.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(temperature).state != STATE_UNAVAILABLE
    assert (
        hass.states.get(camera_entity_id(hass, "3000047_2")).state != STATE_UNAVAILABLE
    )


async def test_camera_unload_inflight_images(
    hass: HomeAssistant,
    camera_entry: MockConfigEntry,
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
    jpeg: bytes,
    freezer: Any,
) -> None:
    """Unloading cancels a scheduled JPEG request, without closing HA's session."""
    await setup_cameras(hass, camera_entry, mock_http, camera_features, jpeg)
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def pending(*_: Any, **__: Any) -> CallbackResult:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return CallbackResult(body=jpeg, content_type="image/jpeg")

    mock_http.get(
        camera_url(("3000047_2", "3000063_1")), payload=page(camera_features[:2])
    )
    mock_http.get(camera_features[0]["properties"]["STILL_IMAGE_URL"], callback=pending)
    mock_http.get(
        camera_features[1]["properties"]["STILL_IMAGE_URL"],
        body=jpeg,
        content_type="image/jpeg",
    )
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass, datetime.now(UTC))
    await asyncio.wait_for(started.wait(), timeout=2)
    assert await hass.config_entries.async_unload(camera_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert cancelled.is_set()


async def test_camera_subentry_reload_retains_identity(
    hass: HomeAssistant,
    camera_entry: MockConfigEntry,
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
    jpeg: bytes,
) -> None:
    """Republishing/renaming and selection changes do not duplicate source devices."""
    await setup_cameras(hass, camera_entry, mock_http, camera_features, jpeg)
    first_id = camera_entity_id(hass, "3000047_2")
    first_device = er.async_get(hass).async_get(first_id).device_id
    old = camera_entry.runtime_data.cameras
    camera_features[0]["properties"]["DESCRIPTION"] = "Renamed public camera"
    camera_features[0]["id"] = "CctvSimple_v2.new-publication"
    mock_http.get(
        camera_url(("1429014_1", "3000047_2", "3000063_1")),
        payload=page(camera_features),
    )
    for feature in camera_features[:2]:
        mock_http.get(
            feature["properties"]["STILL_IMAGE_URL"],
            body=jpeg,
            content_type="image/jpeg",
        )
    extra = ConfigSubentry(
        subentry_type=SUBENTRY_CAMERA,
        unique_id="camera:1429014_1",
        title="Grytadalen",
        data={CONF_CAMERA_ID: "1429014_1"},
    )
    hass.config_entries.async_add_subentry(camera_entry, extra)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert old._shutdown_requested
    assert camera_entity_id(hass, "3000047_2") == first_id
    assert er.async_get(hass).async_get(first_id).device_id == first_device
    assert (
        dr.async_get(hass)
        .async_get(first_device)
        .name.startswith("Renamed public camera")
    )
    extra_id = camera_entity_id(hass, "1429014_1")
    status_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, "camera:1429014_1:availability"
    )
    assert (
        er.async_get(hass).async_get(status_id).device_id
        == er.async_get(hass).async_get(extra_id).device_id
    )
    assert hass.states.get(extra_id).state == STATE_UNAVAILABLE
    mock_camera_poll(mock_http, camera_features, jpeg)
    hass.config_entries.async_remove_subentry(camera_entry, extra.subentry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert er.async_get(hass).async_get(extra_id) is None
    assert er.async_get(hass).async_get(status_id) is None
    assert er.async_get(hass).async_get(first_id).device_id == first_device


@pytest.mark.parametrize("status", [None, "futureStatus"])
async def test_null_or_unknown_status_entity(
    hass: HomeAssistant,
    camera_entry: MockConfigEntry,
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
    jpeg: bytes,
    status: str | None,
) -> None:
    """Keep null/unknown source status faithful without assuming image availability."""
    camera_features[0]["properties"]["STATUS_STILL_IMAGE_AVAILABILITY"] = status
    camera_features[0]["properties"]["STILL_IMAGE_SERVICE_LEVEL"] = 0
    camera_entry.add_to_hass(hass)
    mock_http.get(
        camera_url(("3000047_2", "3000063_1")), payload=page(camera_features[:2])
    )
    mock_http.get(
        camera_features[1]["properties"]["STILL_IMAGE_URL"],
        body=jpeg,
        content_type="image/jpeg",
    )
    assert await hass.config_entries.async_setup(camera_entry.entry_id)
    await hass.async_block_till_done()
    status_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, "camera:3000047_2:availability"
    )
    state = hass.states.get(status_id)
    assert state.state == (STATE_UNKNOWN if status is None else status)
    assert state.attributes["still_image_service_level"] == 0
    assert (
        hass.states.get(camera_entity_id(hass, "3000047_2")).state == STATE_UNAVAILABLE
    )
    assert len(mock_http.requests) == 2


async def test_camera_metadata_rate_limit(
    hass: HomeAssistant,
    camera_entry: MockConfigEntry,
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
    jpeg: bytes,
    freezer: Any,
) -> None:
    """Back off the CCTV collection when its metadata endpoint returns 429."""
    await setup_cameras(hass, camera_entry, mock_http, camera_features, jpeg)
    mock_http.get(
        camera_url(("3000047_2", "3000063_1")),
        status=429,
        headers={"Retry-After": "180"},
    )
    await camera_entry.runtime_data.cameras.async_refresh()
    assert not camera_entry.runtime_data.cameras.last_update_success
    requests = sum(len(items) for items in mock_http.requests.values())
    freezer.tick(timedelta(seconds=61))
    async_fire_time_changed(hass, datetime.now(UTC))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert sum(len(items) for items in mock_http.requests.values()) == requests
    mock_camera_poll(mock_http, camera_features, jpeg)
    freezer.tick(timedelta(seconds=121))
    async_fire_time_changed(hass, datetime.now(UTC))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert camera_entry.runtime_data.cameras.last_update_success
