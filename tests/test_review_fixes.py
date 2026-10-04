"""Regressions for setup cooldowns, action lifecycle and startup-independent names."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from yarl import URL

from custom_components.vegvesen.api import VegvesenRateLimitError
from custom_components.vegvesen.const import (
    CONF_STATION_ID,
    CONF_STATION_NAME,
    DOMAIN,
    SUBENTRY_WEATHER_STATION,
)
from custom_components.vegvesen.discovery import async_get_discovery
from custom_components.vegvesen.route_geometry import make_corridor

from .helpers import camera_url, page, weather_url
from .test_camera import mock_camera_poll
from .test_routes import forecast_url, routing_url, source_entity
from .test_sensor import entity_id

if TYPE_CHECKING:
    from aioresponses import aioresponses
    from homeassistant.core import HomeAssistant


def request_count(mock_http: aioresponses, url: str) -> int:
    """Count requests to an endpoint regardless of filters or query ordering."""
    return sum(
        len(calls)
        for (_, target), calls in mock_http.requests.items()
        if target.with_query(None) == URL(url).with_query(None)
    )


@pytest.mark.parametrize("healthy_weather", [False, True])
async def test_initial_cooldown_survives_retry_reload_and_discovery(
    hass: HomeAssistant,
    camera_entry: MockConfigEntry,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    camera_features: list[dict[str, Any]],
    jpeg: bytes,
    freezer: Any,
    *,
    healthy_weather: bool,
) -> None:
    """HA retries cannot send HTTP before the first-refresh Retry-After expires."""
    camera_entry.add_to_hass(hass)
    if healthy_weather:
        hass.config_entries.async_add_subentry(
            camera_entry,
            ConfigSubentry(
                subentry_type=SUBENTRY_WEATHER_STATION,
                unique_id="weather_station:1629006",
                title="Fv 714 Våvatnet (1629006)",
                data={CONF_STATION_ID: "1629006"},
            ),
        )
        mock_http.get(
            weather_url(("1629006",)), payload=page(features[:1]), repeat=True
        )
    url = camera_url(("3000047_2", "3000063_1"))
    mock_http.get(url, status=429, headers={"Retry-After": "600"})
    assert await hass.config_entries.async_setup(camera_entry.entry_id) == (
        healthy_weather
    )
    assert camera_entry.state is (
        ConfigEntryState.LOADED if healthy_weather else ConfigEntryState.SETUP_RETRY
    )
    shared = async_get_discovery(hass)
    freezer.tick(timedelta(seconds=62))
    async_fire_time_changed(hass, datetime.now(UTC))
    await hass.async_block_till_done(wait_background_tasks=True)
    if healthy_weather:
        await camera_entry.runtime_data.cameras.async_refresh()
        assert camera_entry.runtime_data.weather.last_update_success
    assert await hass.config_entries.async_reload(camera_entry.entry_id) == (
        healthy_weather
    )
    with pytest.raises(VegvesenRateLimitError) as error:
        await shared.cameras.async_get()
    assert error.value.retry_after == 538
    assert request_count(mock_http, url) == 1
    assert async_get_discovery(hass) is shared

    mock_camera_poll(mock_http, camera_features, jpeg)
    freezer.tick(timedelta(seconds=600))
    async_fire_time_changed(hass, datetime.now(UTC))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert camera_entry.state is ConfigEntryState.LOADED
    assert camera_entry.runtime_data.cameras.last_update_success
    assert request_count(mock_http, url) == 2


async def test_later_page_cooldown_covers_other_queries(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    freezer: Any,
) -> None:
    """A failed page cannot be bypassed by restarting discovery or a filtered query."""
    shared = async_get_discovery(hass)
    next_url = weather_url(start_index=1)
    mock_http.get(
        weather_url(), payload=page(features[:1], matched=2, next_url=next_url)
    )
    mock_http.get(next_url, status=429, headers={"Retry-After": "120"})
    with pytest.raises(VegvesenRateLimitError):
        await shared.weather.async_get()
    with pytest.raises(VegvesenRateLimitError):
        await shared.client.async_get_weather({"1629006"})
    with pytest.raises(VegvesenRateLimitError):
        await shared.weather.async_get()
    assert sum(map(len, mock_http.requests.values())) == 2
    mock_http.get(camera_url(), payload=page([]))
    assert await shared.client.async_get_cameras() == {}
    freezer.tick(timedelta(seconds=121))
    mock_http.get(weather_url(), payload=page(features[:2]))
    assert len(await shared.weather.async_get()) == 2


async def test_routing_cooldown_allows_forecast_requests(
    hass: HomeAssistant,
    mock_http: aioresponses,
    route_data: dict[str, Any],
    routing: dict[str, Any],
    freezer: Any,
) -> None:
    """Repeated setup requests share routing backoff without blocking forecasts."""
    client = async_get_discovery(hass).route_client
    stops = [route_data["start"], route_data["end"]]
    url = routing_url(route_data)
    mock_http.get(url, status=429, headers={"Retry-After": "120"})
    with pytest.raises(VegvesenRateLimitError):
        await client.async_routes(stops)
    with pytest.raises(VegvesenRateLimitError):
        await async_get_discovery(hass).route_client.async_routes(stops)
    assert request_count(mock_http, url) == 1
    target = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    bbox = make_corridor(route_data["geometry"], 100).bbox
    mock_http.get(forecast_url(bbox, target), payload=page([]))
    assert await client.async_forecasts(bbox, target) == {}
    freezer.tick(timedelta(seconds=121))
    mock_http.get(url, payload=routing)
    assert await client.async_routes(stops)


async def test_action_exists_before_entries_and_uses_reloaded_runtime(
    hass: HomeAssistant,
    mock_http: aioresponses,
    route_data: dict[str, Any],
    forecasts: list[dict[str, Any]],
    freezer: Any,
) -> None:
    """Keep the action registered during setup retry and use fresh data after reload."""
    assert await async_setup_component(hass, DOMAIN, {})
    assert hass.services.has_service(DOMAIN, "get_route_forecasts")
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="public_service",
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
    target = datetime.fromisoformat(
        forecasts[0]["properties"]["FORECAST_TIME"]
    ).astimezone(UTC)
    freezer.move_to(target - timedelta(minutes=55))
    url = forecast_url(make_corridor(route_data["geometry"], 100).bbox, target)
    mock_http.get(url, payload=page(forecasts))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    device_id = er.async_get(hass).async_get(source_entity(hass, "slip_risk")).device_id
    original = entry.runtime_data
    mock_http.get(url, status=503)
    assert not await hass.config_entries.async_reload(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert hass.services.has_service(DOMAIN, "get_route_forecasts")
    with pytest.raises(ServiceValidationError, match="unavailable"):
        await hass.services.async_call(
            DOMAIN,
            "get_route_forecasts",
            {"device_id": device_id},
            blocking=True,
            return_response=True,
        )
    mock_http.get(url, payload=page(forecasts[:1]))
    assert await hass.config_entries.async_reload(entry.entry_id)
    assert entry.runtime_data is not original
    result = await hass.services.async_call(
        DOMAIN,
        "get_route_forecasts",
        {"device_id": device_id},
        blocking=True,
        return_response=True,
    )
    assert len(result["segments"]) == 1


@pytest.mark.parametrize("saved_name", [False, True])
@pytest.mark.parametrize("existing_entity", [False, True])
async def test_weather_names_during_missing_startup_and_recovery(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    *,
    saved_name: bool,
    existing_entity: bool,
) -> None:
    """Both legacy and new entries retain IDs and user names through source recovery."""
    name = features[0]["properties"]["LOCATION_DESCRIPTION"]
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="public_service",
        subentries_data=[
            {
                "subentry_type": SUBENTRY_WEATHER_STATION,
                "unique_id": "weather_station:1629006",
                "title": f"{name} (1629006)",
                "data": {
                    CONF_STATION_ID: "1629006",
                    **({CONF_STATION_NAME: name} if saved_name else {}),
                },
            }
        ],
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    expected_id = "sensor.fv_714_vavatnet_air_temperature"
    if existing_entity:
        expected_id = registry.async_get_or_create(
            "sensor",
            DOMAIN,
            "weather_station:1629006:air_temperature",
            config_entry=entry,
            config_subentry_id=next(iter(entry.subentries)),
            suggested_object_id="fv_714_vavatnet_1629006_air_temperature",
        ).entity_id
    url = weather_url(("1629006",))
    mock_http.get(url, payload=page([]))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entity_id(hass, "1629006", "air_temperature") == expected_id
    assert hass.states.get(expected_id).state == STATE_UNAVAILABLE
    devices = dr.async_get(hass)
    device = devices.async_get(registry.async_get(expected_id).device_id)
    assert device.name == name
    devices.async_update_device(device.id, name_by_user="My station")
    features[0]["properties"]["LOCATION_DESCRIPTION"] = "Updated source name"
    mock_http.get(url, payload=page(features[:1]))
    await entry.runtime_data.weather.async_refresh()
    await hass.async_block_till_done()
    device = devices.async_get(device.id)
    assert device.name == "Updated source name"
    assert device.name_by_user == "My station"
    assert entity_id(hass, "1629006", "air_temperature") == expected_id
    assert hass.states.get(expected_id).state != STATE_UNAVAILABLE
