"""Exercise dependent-selector metadata and scalar source-ID flow submission."""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.data_entry_flow import FlowManagerIndexView
from homeassistant.helpers.translation import async_get_translations

from custom_components.vegvesen.const import CONF_CAMERA_ID, CONF_STATION_ID, DOMAIN

from .helpers import camera_url, page, weather_url

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
    return manager, result


@pytest.mark.parametrize("family", ["weather_station", "camera"])
@pytest.mark.parametrize("kind", ["parent", "subentry"])
async def test_one_submit_selection(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    camera_features: list[dict[str, Any]],
    camera_entry: MockConfigEntry,
    family: str,
    kind: str,
) -> None:
    """All four paths show only actual sources and require one submission."""
    weather = family == "weather_station"
    records = features if weather else [camera_features[2]]
    endpoint = weather_url if weather else camera_url
    field = CONF_STATION_ID if weather else CONF_CAMERA_ID
    source_id = records[0]["properties"]["REFERENCE_ID" if weather else "CAMERA_ID"]
    mock_http.get(endpoint(), payload=page(records))
    mock_http.get(endpoint((source_id,)), payload=page(records[:1]))
    with patch("custom_components.vegvesen.async_setup_entry", return_value=True):
        manager, result = await start_flow(hass, family, kind, camera_entry)
        assert list(result["data_schema"].schema) == [field]
        selector = result["data_schema"].schema[field]
        assert selector.selector_type == "vegvesen_source"
        serialized = FlowManagerIndexView(
            hass.config_entries.flow
        )._prepare_result_json(result)
        assert serialized["data_schema"][0]["default"] == ""
        assert "vegvesen_source" in serialized["data_schema"][0]["selector"]
        options = selector.config["options"]
        assert len(options) == len(records)
        option = next(option for option in options if option["value"] == source_id)
        assert option["county"] == ("Trøndelag" if weather else "Vestland")
        assert option["municipality"] == ("Orkland" if weather else "Kinn")
        assert source_id in option["label"]
        assert " / " not in option["label"]
        result = await manager.async_configure(result["flow_id"], {field: source_id})
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    if kind == "parent":
        assert result["result"].data == {}
        source = next(iter(result["result"].subentries.values()))
        assert source.data == {field: source_id}
    else:
        assert result["data"] == {field: source_id}
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
    field = CONF_STATION_ID if weather else CONF_CAMERA_ID
    mock_http.get(endpoint(), payload=page(features if weather else camera_features))
    manager, result = await start_flow(hass, family, kind, camera_entry)
    result = await manager.async_configure(result["flow_id"], {field: "Orkland"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {field: "invalid_source"}
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
        options = result["data_schema"].schema[CONF_STATION_ID].config["options"]
        name = feature["properties"]["LOCATION_DESCRIPTION"]
        assert options == [
            {
                "value": source_id,
                "label": f"{name} ({source_id})",
                "county": None,
                "municipality": None,
            }
        ]
        result = await manager.async_configure(
            result["flow_id"], {CONF_STATION_ID: source_id}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_bokmal_picker_translation(hass: HomeAssistant) -> None:
    """Load the one-submit search instructions through HA's translation loader."""
    labels = await async_get_translations(hass, "nb", "config", {DOMAIN})
    text = labels["component.vegvesen.config.step.weather_station.description"]
    assert "én gang" in text
    assert "fylke" in text
    assert "kommune" in text
