"""Native icons, automatic route names and registry-owned entity IDs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.icon import async_get_icons
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vegvesen.const import DOMAIN
from custom_components.vegvesen.route_geometry import make_corridor

from .helpers import finish_progress, menu_action, page
from .test_routes import forecast_url, routing_url

if TYPE_CHECKING:
    from aioresponses import aioresponses
    from homeassistant.core import HomeAssistant


async def test_native_icons(hass: HomeAssistant) -> None:
    """HA loads the custom icon resource; device-class defaults stay in charge."""
    icons = await async_get_icons(hass, "entity", {DOMAIN})
    sensors = icons[DOMAIN]["sensor"]
    assert sensors["route_road_condition"]["default"] == "mdi:road-variant"
    assert sensors["route_slip_risk"]["default"] == "mdi:car-traction-control"
    assert sensors["route_forecast_segments"]["default"] == "mdi:counter"
    assert sensors["source_availability"]["default"] == "mdi:cctv"
    assert "air_temperature" not in sensors
    assert "measurement_time" not in sensors
    assert "route_forecast_time" not in sensors


@pytest.mark.parametrize("kind", ["parent", "subentry"])
@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("zone.home", "zone.work", "Hjem → Jobb"),
        ("zone.home", "map", "Hjem → E6/E39"),
        ("map", "zone.work", "E6/E39 → Jobb"),
        ("map", "map", "E6/E39"),
    ],
)
async def test_automatic_route_names(
    hass: HomeAssistant,
    mock_http: aioresponses,
    routing: dict[str, Any],
    route_data: dict[str, Any],
    kind: str,
    start: str,
    end: str,
    expected: str,
) -> None:
    """Omitting or clearing a name uses endpoint names without extra geocoding."""
    for endpoint, zone, name in (
        ("start", "zone.home", "Hjem"),
        ("end", "zone.work", "Jobb"),
    ):
        hass.states.async_set(
            zone, "0", {**route_data[endpoint], "friendly_name": name}
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
        settings = {
            "start_source": start,
            "end_source": end,
            "corridor_m": 100,
            "forecast_hours": 1,
        }
        mock_http.get(routing_url(route_data), payload=routing)
        result = await manager.async_configure(result["flow_id"], settings)
        if "map" in (start, end):
            result = await manager.async_configure(
                result["flow_id"],
                {
                    endpoint: route_data[endpoint]
                    for endpoint, source in (("start", start), ("end", end))
                    if source == "map"
                },
            )
        result = await finish_progress(manager, result)
        assert result["description_placeholders"]["name"] == expected
        result = await menu_action(manager, result, "route_settings")
        result = await finish_progress(
            manager,
            await manager.async_configure(
                result["flow_id"], {**settings, "name": "  Morning commute  "}
            ),
        )
        if "map" in (start, end):
            result = await finish_progress(
                manager, await manager.async_configure(result["flow_id"], {})
            )
        assert result["description_placeholders"]["name"] == "Morning commute"
        result = await menu_action(manager, result, "route_settings")
        result = await manager.async_configure(result["flow_id"], settings)
        if "map" in (start, end):
            result = await manager.async_configure(result["flow_id"], {})
        result = await finish_progress(manager, result)
        assert result["description_placeholders"]["name"] == expected
        result = await menu_action(manager, result, "route_save")
        if kind == "parent":
            entry = result["result"]
        subentry = next(iter(entry.subentries.values()))
        assert subentry.title == subentry.data["name"] == expected
        assert subentry.unique_id == f"route:{subentry.data['route_id']}"
        assert sum(len(calls) for calls in mock_http.requests.values()) == 1


@pytest.mark.parametrize("language", ["en", "nb"])
async def test_route_entity_ids_survive_renaming(
    hass: HomeAssistant,
    mock_http: aioresponses,
    route_data: dict[str, Any],
    forecasts: list[dict[str, Any]],
    freezer: Any,
    language: str,
) -> None:
    """HA builds readable IDs once, then preserves them and user overrides."""
    hass.config.language = language
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
                "title": "Hjem → Jobb",
                "data": {**route_data, "name": "Hjem → Jobb"},
            }
        ],
    )
    entry.add_to_hass(hass)
    mock_http.get(
        forecast_url(make_corridor(route_data["geometry"], 100).bbox, target),
        payload=page(forecasts),
        repeat=True,
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    unique_id = "route:example-route:road_condition"
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    suffix = "road_condition_forecast" if language == "en" else "foreprognose"
    assert entity_id == f"sensor.hjem_jobb_{suffix}"
    registry.async_update_entity(
        entity_id,
        new_entity_id="sensor.my_commute",
        name="My conditions",
        icon="mdi:car",
    )
    original_ids = {
        item.entity_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    subentry = next(iter(entry.subentries.values()))
    hass.config_entries.async_update_subentry(
        entry,
        subentry,
        title="Renamed route",
        data={**subentry.data, "name": "Renamed route"},
    )
    await hass.async_block_till_done()
    assert {
        item.entity_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
    } == original_ids
    assert (
        registry.async_get_entity_id("sensor", DOMAIN, unique_id) == "sensor.my_commute"
    )
    registered = registry.async_get("sensor.my_commute")
    assert registered.name == "My conditions"
    assert registered.icon == "mdi:car"
    assert hass.states.get("sensor.my_commute") is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
