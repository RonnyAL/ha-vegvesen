"""Regression coverage for native flow cancellation and editable user input."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from aioresponses import CallbackResult
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.data_entry_flow import FlowManagerIndexView
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vegvesen.const import DOMAIN

from .helpers import (
    camera_url,
    choose_region,
    finish_progress,
    page,
    weather_url,
)
from .test_selection import start_flow

if TYPE_CHECKING:
    from aioresponses import aioresponses
    from homeassistant.core import HomeAssistant


@pytest.mark.parametrize("family", ["weather_station", "camera"])
async def test_cached_subentry_discovery_returns_county(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    camera_features: list[dict[str, Any]],
    family: str,
) -> None:
    """A warm cache returns its county form without a progress event race."""
    weather = family == "weather_station"
    endpoint = weather_url if weather else camera_url
    mock_http.get(endpoint(), payload=page(features if weather else camera_features))
    entry = MockConfigEntry(domain=DOMAIN, unique_id="public_service", data={})
    with patch(
        "custom_components.vegvesen.discovery._read_source_geography", return_value={}
    ):
        manager, first = await start_flow(hass, family, "subentry", entry)
        manager.async_abort(first["flow_id"])
        result = await manager.async_init(
            (entry.entry_id, family), context={"source": SOURCE_USER}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "county"
    assert sum(map(len, mock_http.requests.values())) == 1
    assert not entry.subentries
    manager.async_abort(result["flow_id"])


@pytest.mark.parametrize("kind", ["parent", "subentry"])
@pytest.mark.parametrize("family", ["weather_station", "camera"])
async def test_clear_source_draft(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    camera_features: list[dict[str, Any]],
    kind: str,
    family: str,
) -> None:
    """Omitting a cleared selector must not restore its old selection."""
    weather = family == "weather_station"
    records = features if weather else camera_features
    endpoint = weather_url if weather else camera_url
    source_id = records[0]["properties"]["REFERENCE_ID" if weather else "CAMERA_ID"]
    entry = MockConfigEntry(domain=DOMAIN, unique_id="public_service", data={})
    mock_http.get(endpoint(), payload=page(records))
    with patch(
        "custom_components.vegvesen.discovery._read_source_geography", return_value={}
    ):
        manager, result = await start_flow(hass, family, kind, entry)
        result = await choose_region(manager, result, "unknown", "unknown")
    mock_http.get(endpoint((source_id,)), status=503)
    result = await manager.async_configure(result["flow_id"], {"sources": [source_id]})
    result = await finish_progress(manager, result)
    assert result["errors"] == {"base": "cannot_connect"}
    serialized = FlowManagerIndexView(manager)._prepare_result_json(result)
    assert serialized["data_schema"][0]["description"]["suggested_value"] == [source_id]
    result = await manager.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "no_sources_selected"}
    assert next(iter(result["data_schema"].schema)).description == {
        "suggested_value": []
    }
    assert not entry.subentries
    assert sum(map(len, mock_http.requests.values())) == 2
    manager.async_abort(result["flow_id"])


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("forecast_hours", 1.5, "invalid_forecast_hours"),
        ("forecast_hours", "nan", "invalid_forecast_hours"),
        ("corridor_m", "nan", "invalid_corridor"),
    ],
)
@pytest.mark.parametrize("kind", ["parent", "subentry"])
async def test_route_numeric_validation(
    hass: HomeAssistant,
    mock_http: aioresponses,
    kind: str,
    field: str,
    value: Any,
    error: str,
) -> None:
    """Reject invalid settings before routing or storage."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="public_service", data={})
    manager, result = await start_flow(hass, "route", kind, entry)
    settings = {
        "name": "Example",
        "start_source": "map",
        "end_source": "map",
        "corridor_m": 100,
        "forecast_hours": 1,
    }
    result = await manager.async_configure(
        result["flow_id"], {**settings, field: value}
    )
    assert result["step_id"] == "route_settings"
    assert result["errors"] == {field: error}
    # Error forms must remain valid JSON even if a coerced input was NaN.
    json.dumps(
        FlowManagerIndexView(manager)._prepare_result_json(result), allow_nan=False
    )
    result = await manager.async_configure(result["flow_id"], settings)
    assert result["step_id"] == "route_locations"
    assert not mock_http.requests
    assert not entry.subentries
    manager.async_abort(result["flow_id"])


@pytest.mark.parametrize("kind", ["parent", "subentry"])
@pytest.mark.parametrize("family", ["weather_station", "camera"])
@pytest.mark.parametrize("stage", ["discovery", "validation"])
async def test_source_progress_cancellation(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    camera_features: list[dict[str, Any]],
    kind: str,
    family: str,
    stage: str,
) -> None:
    """Closing a slow flow cancels its request and never saves part of a batch."""
    weather = family == "weather_station"
    records = features if weather else camera_features
    endpoint = weather_url if weather else camera_url
    ids = [r["properties"]["REFERENCE_ID" if weather else "CAMERA_ID"] for r in records]
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def slow_response(*_args: Any, **_kwargs: Any) -> CallbackResult:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return CallbackResult(payload=page(records))

    entry = MockConfigEntry(domain=DOMAIN, unique_id="public_service", data={})
    if stage == "discovery":
        mock_http.get(endpoint(), callback=slow_response)
    else:
        mock_http.get(endpoint(), payload=page(records))
        mock_http.get(endpoint(tuple(ids)), callback=slow_response)
    with patch(
        "custom_components.vegvesen.discovery._read_source_geography", return_value={}
    ):
        if kind == "parent":
            manager = hass.config_entries.flow
            result = await manager.async_init(DOMAIN, context={"source": SOURCE_USER})
            result = await manager.async_configure(
                result["flow_id"], {"next_step_id": family}
            )
        else:
            entry.add_to_hass(hass)
            manager = hass.config_entries.subentries
            result = await manager.async_init(
                (entry.entry_id, family), context={"source": SOURCE_USER}
            )
        if stage == "validation":
            result = await finish_progress(manager, result)
            result = await choose_region(manager, result, "unknown", "unknown")
            result = await manager.async_configure(result["flow_id"], {"sources": ids})
        assert result["type"] is FlowResultType.SHOW_PROGRESS
        await asyncio.wait_for(entered.wait(), 1)
        # Reopening the progress screen must not start a second request.
        again = await manager.async_configure(result["flow_id"])
        assert again["type"] is FlowResultType.SHOW_PROGRESS
        assert sum(map(len, mock_http.requests.values())) == (
            1 if stage == "discovery" else 2
        )
        manager.async_abort(result["flow_id"])
        await asyncio.wait_for(cancelled.wait(), 1)
        await hass.async_block_till_done()
    assert not entry.subentries
    assert not manager.async_progress()
    if kind == "parent":
        assert not hass.config_entries.async_entries(DOMAIN)


@pytest.mark.parametrize("language", ["en", "nb"])
async def test_native_progress_translations(hass: HomeAssistant, language: str) -> None:
    """Progress actions and input errors have native translations."""
    for category in ["config", "config_subentries"]:
        labels = await async_get_translations(hass, language, category, {DOMAIN})
        prefixes = (
            [f"component.{DOMAIN}.config"]
            if category == "config"
            else [
                f"component.{DOMAIN}.config_subentries.{family}"
                for family in ["weather_station", "camera", "route"]
            ]
        )
        for prefix in prefixes:
            actions = (
                ["calculate_route"]
                if prefix.endswith(".route")
                else ["load_sources", "validate_sources"]
            )
            if category == "config":
                actions.append("calculate_route")
            for action in actions:
                assert labels[f"{prefix}.progress.{action}"]
            if category == "config" or prefix.endswith(".route"):
                assert labels[f"{prefix}.error.invalid_forecast_hours"]
                assert labels[f"{prefix}.error.invalid_corridor"]


@pytest.mark.parametrize("kind", ["parent", "subentry", "reconfigure"])
async def test_route_calculation_cancellation(
    hass: HomeAssistant,
    mock_http: aioresponses,
    routing: dict[str, Any],
    route_data: dict[str, Any],
    kind: str,
) -> None:
    """HA cancels slow route requests without creating or editing saved routes."""
    from copy import deepcopy  # noqa: PLC0415

    from .test_routes import routing_url  # noqa: PLC0415

    original = deepcopy(route_data)
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
        ]
        if kind == "reconfigure"
        else [],
    )
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def slow_response(*_args: Any, **_kwargs: Any) -> CallbackResult:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return CallbackResult(payload=routing)

    mock_http.get(routing_url(route_data), callback=slow_response)
    if kind == "reconfigure":
        entry.add_to_hass(hass)
        manager = hass.config_entries.subentries
        subentry = next(iter(entry.subentries.values()))
        result = await manager.async_init(
            (entry.entry_id, "route"),
            context={"source": "reconfigure", "subentry_id": subentry.subentry_id},
        )
        result = await manager.async_configure(
            result["flow_id"], {"next_step_id": "route_recalculate"}
        )
    else:
        manager, result = await start_flow(hass, "route", kind, entry)
        result = await manager.async_configure(
            result["flow_id"],
            {
                **{
                    key: route_data[key]
                    for key in ["name", "corridor_m", "forecast_hours"]
                },
                "start_source": "map",
                "end_source": "map",
            },
        )
        result = await manager.async_configure(
            result["flow_id"], {key: route_data[key] for key in ["start", "end"]}
        )
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["progress_action"] == "calculate_route"
    await asyncio.wait_for(entered.wait(), 1)
    again = await manager.async_configure(result["flow_id"])
    assert again["type"] is FlowResultType.SHOW_PROGRESS
    assert sum(map(len, mock_http.requests.values())) == 1
    manager.async_abort(result["flow_id"])
    await asyncio.wait_for(cancelled.wait(), 1)
    await hass.async_block_till_done()
    if kind == "reconfigure":
        assert dict(subentry.data) == original
    else:
        assert not entry.subentries
    assert not manager.async_progress()


@pytest.mark.parametrize("kind", ["parent", "subentry"])
async def test_current_hour_default_and_translation(
    hass: HomeAssistant, kind: str
) -> None:
    """Native forms default to zero, accept it, and translate the unit suffix."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="public_service", data={})
    manager, result = await start_flow(hass, "route", kind, entry)
    serialized = FlowManagerIndexView(manager)._prepare_result_json(result)
    field = next(f for f in serialized["data_schema"] if f["name"] == "forecast_hours")
    assert field["default"] == 0
    assert field["selector"]["number"]["min"] == 0
    assert field["selector"]["number"]["max"] == 24
    assert field["selector"]["number"]["translation_key"] == "forecast_hours"
    for language, unit in [("en", "hours"), ("nb", "timer")]:
        labels = await async_get_translations(hass, language, "selector", {DOMAIN})
        assert (
            labels[f"component.{DOMAIN}.selector.forecast_hours.unit_of_measurement.h"]
            == unit
        )
    result = await manager.async_configure(
        result["flow_id"],
        {
            "name": "Example",
            "start_source": "map",
            "end_source": "map",
            "corridor_m": 100,
            "forecast_hours": 0,
        },
    )
    assert result["step_id"] == "route_locations"
    manager.async_abort(result["flow_id"])
