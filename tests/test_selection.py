"""Exercise categorized source browsing through the actual HA flow managers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.translation import async_get_translations

from custom_components.vegvesen.const import (
    CONF_CAMERA_ID,
    CONF_STATION_ID,
    DOMAIN,
)
from custom_components.vegvesen.geography import GEOGRAPHY_URL
from custom_components.vegvesen.selection import ALL, CONF_COUNTY, CONF_MUNICIPALITY

from .helpers import camera_url, page, weather_url
from .test_geography import point_payload, point_url

if TYPE_CHECKING:
    from aioresponses import aioresponses
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


async def start_flow(hass: HomeAssistant, family: str, kind: str, entry: Any) -> Any:
    """Open the right parent or subentry source picker."""
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
async def test_categorized_selection(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    camera_features: list[dict[str, Any]],
    camera_entry: MockConfigEntry,
    family: str,
    kind: str,
) -> None:
    """County then municipality narrows all four selection paths, preserving IDs."""
    weather = family == "weather_station"
    records = features if weather else camera_features
    endpoint = weather_url if weather else camera_url
    field = CONF_STATION_ID if weather else CONF_CAMERA_ID
    # This existing camera parent does not already own the weather source.
    entry = camera_entry
    if not weather:
        records = [camera_features[2]]
    source_id = records[0]["properties"]["REFERENCE_ID" if weather else "CAMERA_ID"]
    county, municipality = ("50", "5059") if weather else ("46", "4602")
    mock_http.get(endpoint(), payload=page(records))
    mock_http.get(endpoint((source_id,)), payload=page(records[:1]))
    for record in records:
        longitude, latitude = record["geometry"]["coordinates"]
        mock_http.get(
            point_url(latitude, longitude), payload=point_payload(county, municipality)
        )
    with patch("custom_components.vegvesen.async_setup_entry", return_value=True):
        manager, result = await start_flow(hass, family, kind, entry)
        assert field not in result["data_schema"].schema
        result = await manager.async_configure(result["flow_id"], {CONF_COUNTY: county})
        options = result["data_schema"].schema[CONF_MUNICIPALITY].config["options"]
        assert any(option["value"] == municipality for option in options)
        assert field not in result["data_schema"].schema
        result = await manager.async_configure(
            result["flow_id"], {CONF_COUNTY: county, CONF_MUNICIPALITY: municipality}
        )
        options = result["data_schema"].schema[field].config["options"]
        assert source_id in {option["value"] for option in options}
        result = await manager.async_configure(
            result["flow_id"],
            {CONF_COUNTY: county, CONF_MUNICIPALITY: municipality, field: source_id},
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    if kind == "parent":
        assert result["result"].data == {}
        created = next(iter(result["result"].subentries.values()))
        assert created.data == {field: source_id}
    else:
        assert result["data"] == {field: source_id}


@pytest.mark.parametrize("kind", ["parent", "subentry"])
@pytest.mark.parametrize("family", ["weather_station", "camera"])
async def test_geography_failure_all_norway_escape(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    camera_features: list[dict[str, Any]],
    camera_entry: MockConfigEntry,
    kind: str,
    family: str,
) -> None:
    """Failed geography cannot block nationwide discovery or source selection."""
    mock_http.clear()
    weather = family == "weather_station"
    field = CONF_STATION_ID if weather else CONF_CAMERA_ID
    mock_http.get(
        weather_url() if weather else camera_url(),
        payload=page(features if weather else camera_features),
    )
    mock_http.get(f"{GEOGRAPHY_URL}/fylkerkommuner?utkoordsys=4326", status=503)
    manager, result = await start_flow(hass, family, kind, camera_entry)
    assert result["errors"] == {"base": "geography_unavailable"}
    result = await manager.async_configure(result["flow_id"], {CONF_COUNTY: ALL})
    assert result["errors"] == {}
    assert len(result["data_schema"].schema[field].config["options"]) == 3
    result = await manager.async_configure(result["flow_id"], {CONF_COUNTY: ALL})
    assert result["errors"] == {"base": "select_source"}


async def test_point_failure_recovery_and_region_change(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    camera_entry: MockConfigEntry,
) -> None:
    """Failed membership never offers partial choices; changing county resets them."""
    mock_http.get(weather_url(), payload=page(features))
    manager, result = await start_flow(
        hass, "weather_station", "subentry", camera_entry
    )
    result = await manager.async_configure(result["flow_id"], {CONF_COUNTY: "50"})
    url = point_url(*reversed(features[0]["geometry"]["coordinates"]))
    other = point_url(*reversed(features[2]["geometry"]["coordinates"]))
    mock_http.get(url, status=503)
    mock_http.get(other, payload=point_payload("50", "5059"), repeat=True)
    area = {CONF_COUNTY: "50", CONF_MUNICIPALITY: "5059"}
    result = await manager.async_configure(result["flow_id"], area)
    assert result["errors"] == {"base": "geography_unavailable"}
    assert CONF_STATION_ID not in result["data_schema"].schema
    mock_http.get(url, payload=point_payload("50", "5059"))
    result = await manager.async_configure(result["flow_id"], area)
    assert result["errors"] == {}
    assert len(result["data_schema"].schema[CONF_STATION_ID].config["options"]) == 2
    # Submitting an old source while changing county only advances browsing.
    result = await manager.async_configure(
        result["flow_id"], {CONF_COUNTY: "15", CONF_STATION_ID: "1629006"}
    )
    assert result["type"] is FlowResultType.FORM
    assert CONF_STATION_ID not in result["data_schema"].schema
    assert len(camera_entry.subentries) == 2


async def test_empty_area_and_change_region(
    hass: HomeAssistant,
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
    camera_entry: MockConfigEntry,
) -> None:
    """An empty region can be changed without restarting or saving geography."""
    mock_http.get(camera_url(), payload=page(camera_features))
    manager, result = await start_flow(hass, "camera", "subentry", camera_entry)
    result = await manager.async_configure(result["flow_id"], {CONF_COUNTY: "50"})
    result = await manager.async_configure(
        result["flow_id"], {CONF_COUNTY: "50", CONF_MUNICIPALITY: "5059"}
    )
    assert result["errors"] == {"base": "no_sources_in_area"}
    assert CONF_CAMERA_ID not in result["data_schema"].schema
    result = await manager.async_configure(result["flow_id"], {CONF_COUNTY: ALL})
    assert len(result["data_schema"].schema[CONF_CAMERA_ID].config["options"]) == 3
    assert result["errors"] == {}
    assert len(camera_entry.subentries) == 2


async def test_bokmal_geography_translations(hass: HomeAssistant) -> None:
    """Load localized picker labels and escape hatches through HA's loader."""
    labels = await async_get_translations(hass, "nb", "selector", {DOMAIN})
    assert labels["component.vegvesen.selector.county.options.all"] == "Hele Norge"
    assert (
        labels["component.vegvesen.selector.municipality.options.all"]
        == "Alle kommuner"
    )
