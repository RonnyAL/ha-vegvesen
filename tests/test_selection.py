"""Exercise native hierarchical forms, filtering and source-ID submission."""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers.data_entry_flow import FlowManagerIndexView
from homeassistant.helpers.translation import async_get_translations

from custom_components.vegvesen.const import CONF_CAMERA_ID, CONF_STATION_ID, DOMAIN
from custom_components.vegvesen.selection import CONF_SOURCES

from .helpers import (
    camera_url,
    choose_region,
    finish_progress,
    page,
    save_sources,
    weather_url,
)

if TYPE_CHECKING:
    from aioresponses import aioresponses
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


async def start_flow(hass: HomeAssistant, family: str, kind: str, entry: Any) -> Any:
    """Open a parent or subentry source picker."""
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
    return manager, await finish_progress(manager, result)


@pytest.mark.parametrize("family", ["weather_station", "camera"])
@pytest.mark.parametrize("kind", ["parent", "subentry"])
async def test_native_hierarchical_selection(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    camera_features: list[dict[str, Any]],
    camera_entry: MockConfigEntry,
    family: str,
    kind: str,
) -> None:
    """All four paths serialize native selectors and save source identity metadata."""
    weather = family == "weather_station"
    records = features if weather else [camera_features[2]]
    endpoint = weather_url if weather else camera_url
    field = CONF_STATION_ID if weather else CONF_CAMERA_ID
    source_id = records[0]["properties"]["REFERENCE_ID" if weather else "CAMERA_ID"]
    mock_http.get(endpoint(), payload=page(records))
    mock_http.get(endpoint((source_id,)), payload=page(records[:1]))
    with patch("custom_components.vegvesen.async_setup_entry", return_value=True):
        manager, result = await start_flow(hass, family, kind, camera_entry)
        assert result["step_id"] == "county"
        assert result["last_step"] is False
        county = "Trøndelag" if weather else "Vestland"
        municipality = "Orkland" if weather else "Kinn"
        result = await choose_region(manager, result, county, municipality)
        assert list(result["data_schema"].schema) == [CONF_SOURCES]
        selector = result["data_schema"].schema[CONF_SOURCES]
        assert selector.selector_type == "select"
        assert selector.config["mode"] == "list"
        assert not selector.config["custom_value"]
        assert selector.config["multiple"]
        serialized = FlowManagerIndexView(
            hass.config_entries.flow
        )._prepare_result_json(result)
        assert "select" in serialized["data_schema"][0]["selector"]
        assert serialized["data_schema"][0]["required"]
        options = selector.config["options"]
        assert {option["value"] for option in options} == (
            {"1629006", "1629004"} if weather else {source_id}
        )
        option = next(option for option in options if option["value"] == source_id)
        assert source_id in option["label"]
        assert " / " not in option["label"]
        result = await save_sources(manager, result, source_id)
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    expected = {field: source_id}
    if weather:
        expected["station_name"] = records[0]["properties"]["LOCATION_DESCRIPTION"]
    if kind == "parent":
        assert result["result"].data == {}
        source = next(iter(result["result"].subentries.values()))
        assert source.data == expected
    else:
        assert result["data"] == expected
    assert len(mock_http.requests) == 2  # Catalogue and selected source; no geography.


@pytest.mark.parametrize("family", ["weather_station", "camera"])
@pytest.mark.parametrize("kind", ["parent", "subentry"])
async def test_unknown_source_id_is_rejected(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    camera_features: list[dict[str, Any]],
    camera_entry: MockConfigEntry,
    family: str,
    kind: str,
) -> None:
    """Unknown client input never creates a source or makes a lookup."""
    weather = family == "weather_station"
    endpoint = weather_url if weather else camera_url
    mock_http.get(endpoint(), payload=page(features if weather else camera_features))
    manager, result = await start_flow(hass, family, kind, camera_entry)
    result = await choose_region(
        manager,
        result,
        "Trøndelag" if weather else "Vestland",
        "Orkland" if weather else "Kinn",
    )
    with pytest.raises(InvalidData):
        await manager.async_configure(
            result["flow_id"], {CONF_SOURCES: ["not_a_source"]}
        )
    assert len(mock_http.requests) == 1
    assert len(camera_entry.subentries) == 2


@pytest.mark.parametrize("geography", ["missing", "invalid", "moved", "new", "null"])
async def test_unclassified_sources_remain_selectable(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    camera_entry: MockConfigEntry,
    geography: str,
) -> None:
    """Unavailable or outdated UI geography never hides or misclassifies sources."""
    feature = deepcopy(features[0])
    if geography == "moved":
        feature["geometry"]["coordinates"][0] += 1
    elif geography == "new":
        feature["properties"]["REFERENCE_ID"] = "new_source_id"
    elif geography == "null":
        feature["geometry"] = None
    source_id = feature["properties"]["REFERENCE_ID"]
    mock_http.get(weather_url(), payload=page([feature]))
    mock_http.get(weather_url((source_id,)), payload=page([feature]))
    failure = (
        patch(
            "custom_components.vegvesen.discovery._read_source_geography",
            side_effect=OSError() if geography == "missing" else ValueError(),
        )
        if geography in {"missing", "invalid"}
        else nullcontext()
    )
    with failure:
        manager, result = await start_flow(
            hass, "weather_station", "subentry", camera_entry
        )
        result = await choose_region(manager, result, "unknown", "unknown")
        options = result["data_schema"].schema[CONF_SOURCES].config["options"]
        name = feature["properties"]["LOCATION_DESCRIPTION"]
        assert options == [
            {
                "value": source_id,
                "label": f"{name} ({source_id})",
            }
        ]
        result = await save_sources(manager, result, source_id)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_bokmal_picker_translation(hass: HomeAssistant) -> None:
    """Labels are translated without obvious instructions or attribution clutter."""
    labels = await async_get_translations(hass, "nb", "config", {DOMAIN})
    assert labels["component.vegvesen.config.step.county.title"] == "Fylke"
    assert labels["component.vegvesen.config.step.municipality.title"] == "Kommune"
    assert all("kartverket" not in value.lower() for value in labels.values())
    selectors = await async_get_translations(hass, "nb", "selector", {DOMAIN})
    assert (
        selectors["component.vegvesen.selector.county.options.unknown"]
        == "Ukjent fylke"
    )
    assert (
        selectors["component.vegvesen.selector.municipality.options.unknown"]
        == "Ukjent kommune"
    )


@pytest.mark.parametrize("family", ["weather_station", "camera"])
@pytest.mark.parametrize("kind", ["parent", "subentry"])
async def test_regions_and_sources_are_prefiltered(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    camera_features: list[dict[str, Any]],
    camera_entry: MockConfigEntry,
    family: str,
    kind: str,
) -> None:
    """Every native path excludes empty regions and sources in other municipalities."""
    weather = family == "weather_station"
    mock_http.get(
        weather_url() if weather else camera_url(),
        payload=page(features if weather else camera_features),
    )
    manager, result = await start_flow(hass, family, kind, camera_entry)
    assert result["step_id"] == "county"
    county_options = result["data_schema"].schema["county"].config["options"]
    assert {option["value"] for option in county_options} == (
        {"Trøndelag"} if weather else {"Møre og Romsdal", "Vestland"}
    )
    with pytest.raises(InvalidData):
        await manager.async_configure(result["flow_id"], {"county": "Oslo"})
    result = await manager.async_configure(
        result["flow_id"], {"county": "Trøndelag" if weather else "Vestland"}
    )
    assert result["step_id"] == "municipality"
    municipalities = result["data_schema"].schema["municipality"].config["options"]
    assert {option["value"] for option in municipalities} == (
        {"Orkland", "Åfjord"} if weather else {"Bremanger", "Kinn"}
    )
    with pytest.raises(InvalidData):
        await manager.async_configure(result["flow_id"], {"municipality": "Herøy"})
    result = await manager.async_configure(
        result["flow_id"], {"municipality": "Åfjord" if weather else "Kinn"}
    )
    assert result["step_id"] == f"{family}_sources"
    options = result["data_schema"].schema[CONF_SOURCES].config["options"]
    assert {option["value"] for option in options} == (
        {"1629013"} if weather else {"1429014_1"}
    )
    with pytest.raises(InvalidData):
        await manager.async_configure(
            result["flow_id"], {CONF_SOURCES: ["1629006" if weather else "3000047_2"]}
        )
    assert len(mock_http.requests) == 1


@pytest.mark.parametrize("family", ["weather_station", "camera"])
@pytest.mark.parametrize("kind", ["parent", "subentry"])
async def test_cancel_and_restart_selection(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    camera_features: list[dict[str, Any]],
    camera_entry: MockConfigEntry,
    family: str,
    kind: str,
) -> None:
    """Cancelling a region/source form saves nothing; restarting uses the cache."""
    weather = family == "weather_station"
    mock_http.get(
        weather_url() if weather else camera_url(),
        payload=page(features if weather else camera_features),
    )
    manager, result = await start_flow(hass, family, kind, camera_entry)
    assert result["step_id"] == "county"
    result = await choose_region(
        manager,
        result,
        "Trøndelag" if weather else "Vestland",
        "Orkland" if weather else "Kinn",
    )
    assert result["last_step"] is True
    manager.async_abort(result["flow_id"])
    if kind == "parent":
        result = await manager.async_init(DOMAIN, context={"source": SOURCE_USER})
        result = await manager.async_configure(
            result["flow_id"], {"next_step_id": family}
        )
    else:
        result = await manager.async_init(
            (camera_entry.entry_id, family), context={"source": SOURCE_USER}
        )
    result = await finish_progress(manager, result)
    assert result["step_id"] == "county"
    assert next(iter(result["data_schema"].schema)).default() == ""
    assert len(mock_http.requests) == 1
    assert len(camera_entry.subentries) == 2
    manager.async_abort(result["flow_id"])


@pytest.mark.parametrize("language", ["en", "nb"])
@pytest.mark.parametrize("category", ["config", "config_subentries"])
async def test_translated_wizard_fields(
    hass: HomeAssistant, language: str, category: str
) -> None:
    """Both flow categories use localized fields and HA's standard action labels."""
    resources = await async_get_translations(hass, language, category, {DOMAIN})
    for family in ["weather_station", "camera"]:
        prefix = (
            f"component.{DOMAIN}.config.step"
            if category == "config"
            else f"component.{DOMAIN}.config_subentries.{family}.step"
        )
        assert resources[f"{prefix}.county.data.county"] == (
            "Fylke" if language == "nb" else "County"
        )
        assert resources[f"{prefix}.municipality.data.municipality"] == (
            "Kommune" if language == "nb" else "Municipality"
        )
        assert not any(f"{prefix}.{family}_overview" in key for key in resources)
        for step in ["county", "municipality", f"{family}_sources"]:
            assert f"{prefix}.{step}.submit" not in resources
        assert resources[f"{prefix}.{family}_sources.data.sources"]
        assert all("kartverket_url" not in value for value in resources.values())
