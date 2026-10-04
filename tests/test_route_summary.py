"""Highest source grade and opt-in counts, including missing and new source codes."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vegvesen.const import DOMAIN
from custom_components.vegvesen.route_geometry import make_corridor
from custom_components.vegvesen.route_sensor import COUNT_SENSORS

from .helpers import page
from .test_routes import forecast_url, source_entity


@pytest.mark.parametrize(
    ("grades", "expected", "missing", "unrecognized"),
    [
        (["low", "medium", "high"], "high", 0, 0),
        (["low", "medium", None], "medium", 1, 0),
        (["high", None, "ErrorOrNoData"], "high", 2, 0),
        (["low", "FutureGrade", None], "low", 1, 1),
        ([None, "ErrorOrNoData", None], "unknown", 3, 0),
        (["FutureGrade"] * 3, "unknown", 0, 3),
        ([], "unknown", 0, 0),
    ],
)
async def test_summary_entities(
    hass: Any,
    mock_http: Any,
    route_data: dict,
    forecasts: list,
    freezer: Any,
    grades: list,
    expected: str,
    missing: int,
    unrecognized: int,
) -> None:
    """Expose supplied grades/counts without safe/unsafe inference or silent gaps."""
    target = datetime.fromisoformat(
        forecasts[0]["properties"]["FORECAST_TIME"]
    ).astimezone(UTC)
    route_data["forecast_hours"] = 0
    freezer.move_to(target + timedelta(minutes=10))
    forecasts = forecasts[: len(grades)]
    for forecast, grade in zip(forecasts, grades, strict=True):
        forecast["properties"]["SLIP_RISK"] = grade
        forecast["properties"]["ROAD_CONDITION"] = "IceOrFrost"
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="public_service",
        subentries_data=[
            {
                "subentry_type": "route",
                "unique_id": "route:example-route",
                "title": "Public route",
                "data": route_data,
            }
        ],
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    # Explicitly opted-in entities retain their enabled state during setup.
    for key in ("high_slip_risk_segments", "ice_or_frost_segments"):
        registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"route:example-route:{key}",
            config_entry=entry,
            config_subentry_id=next(iter(entry.subentries)),
        )
    url = forecast_url(make_corridor(route_data["geometry"], 100).bbox, target)
    mock_http.get(url, payload=page(forecasts))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    highest = hass.states.get(source_entity(hass, "highest_slip_risk"))
    assert highest.state == expected
    assert highest.attributes["missing_segments"] == missing
    assert highest.attributes["unrecognized_segments"] == unrecognized
    assert highest.attributes["source_categories"].get("FutureGrade", 0) == unrecognized
    assert "geometry" not in highest.attributes
    count = hass.states.get(source_entity(hass, "high_slip_risk_segments"))
    assert count.state == (
        str(grades.count("high")) if expected != "unknown" else "unknown"
    )
    ice = hass.states.get(source_entity(hass, "ice_or_frost_segments"))
    assert ice.state == (str(len(grades)) if grades else "unknown")
    assert ice.attributes["unit_of_measurement"] == "segments"
    for key in COUNT_SENSORS.keys() - {
        "high_slip_risk_segments",
        "ice_or_frost_segments",
    }:
        item = registry.async_get(source_entity(hass, key))
        assert item.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert hass.states.get(item.entity_id) is None
    coordinator = next(iter(entry.runtime_data.routes.values()))
    assert coordinator.data.forecast_time == target
    mock_http.get(url, status=503)
    await coordinator.async_refresh()
    assert hass.states.get(highest.entity_id).state == "unavailable"
    assert hass.states.get(count.entity_id).state == "unavailable"
    mock_http.get(url, payload=page(forecasts))
    await coordinator.async_refresh()
    assert hass.states.get(highest.entity_id).state == expected
    assert await hass.config_entries.async_unload(entry.entry_id)
