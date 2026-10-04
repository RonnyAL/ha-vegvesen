"""Exercise parent and station subentry flows through HA's flow managers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.vegvesen.const import (
    CONF_STATION_ID,
    DOMAIN,
    SUBENTRY_WEATHER_STATION,
)

from .helpers import choose_region, finish_progress, page, save_sources, weather_url

if TYPE_CHECKING:
    from aioresponses import aioresponses
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_parent_flow(
    hass: HomeAssistant, mock_http: aioresponses, features: list[dict[str, Any]]
) -> None:
    """Choose a readable source ID and create one parent with its first station."""
    mock_http.get(weather_url(), payload=page(features))
    mock_http.get(weather_url(("1629006",)), payload=page(features[:1]))
    with patch("custom_components.vegvesen.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await finish_progress(hass.config_entries.flow, result)
        assert result["type"] is FlowResultType.MENU
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": SUBENTRY_WEATHER_STATION}
        )
        result = await finish_progress(hass.config_entries.flow, result)
        assert result["type"] is FlowResultType.MENU
        result = await choose_region(hass.config_entries.flow, result)
        selector = result["data_schema"].schema["sources"]
        options = selector.config["options"]
        assert any(
            option["value"] == "1629006"
            and "Våvatnet" in option["label"]
            and "1629006" in option["label"]
            for option in options
        )
        result = await save_sources(hass.config_entries.flow, result, "1629006")
        await hass.async_block_till_done()
    result = await finish_progress(hass.config_entries.flow, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.unique_id == "public_service"
    assert entry.data == {}
    subentry = next(iter(entry.subentries.values()))
    assert subentry.subentry_type == SUBENTRY_WEATHER_STATION
    assert subentry.data == {CONF_STATION_ID: "1629006"}
    assert subentry.unique_id == "weather_station:1629006"
    duplicate = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert duplicate["type"] is FlowResultType.ABORT
    assert duplicate["reason"] == "single_instance_allowed"


@pytest.mark.parametrize("failure", ["request", "incomplete", "empty"])
async def test_parent_discovery_failure_recovery(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    failure: str,
) -> None:
    """Unavailable discovery stays in the form and can be retried."""
    if failure == "request":
        mock_http.get(weather_url(), status=503)
    else:
        mock_http.get(
            weather_url(), payload=page([], matched=1 if failure == "incomplete" else 0)
        )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": SUBENTRY_WEATHER_STATION}
    )
    result = await finish_progress(hass.config_entries.flow, result)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == (
        "no_stations" if failure == "empty" else "cannot_connect"
    )
    mock_http.get(weather_url(), payload=page(features))
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await finish_progress(hass.config_entries.flow, result)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["county"]


@pytest.mark.parametrize("missing", [False, True])
async def test_parent_selection_failure(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    missing: bool,  # noqa: FBT001 - pytest supplies parametrized arguments
) -> None:
    """Validate a cached selection against a fresh filtered response."""
    mock_http.get(weather_url(), payload=page(features))
    if missing:
        mock_http.get(weather_url(("1629006",)), payload=page([]))
    else:
        mock_http.get(weather_url(("1629006",)), status=503)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": SUBENTRY_WEATHER_STATION}
    )
    result = await choose_region(hass.config_entries.flow, result)
    result = await save_sources(hass.config_entries.flow, result, "1629006")
    result = await finish_progress(hass.config_entries.flow, result)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {
        "base": "station_missing" if missing else "cannot_connect"
    }
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_add_station_and_duplicate(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    config_entry: MockConfigEntry,
) -> None:
    """Multiple distinct stations share the parent; duplicate IDs are rejected."""
    config_entry.add_to_hass(hass)
    mock_http.get(weather_url(), payload=page(features), repeat=True)
    mock_http.get(weather_url(("1629004",)), payload=page(features[2:]))
    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, SUBENTRY_WEATHER_STATION),
        context={"source": SOURCE_USER},
    )
    result = await choose_region(hass.config_entries.subentries, result)
    result = await save_sources(hass.config_entries.subentries, result, "1629004")
    result = await finish_progress(hass.config_entries.subentries, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(config_entry.subentries) == 3
    duplicate = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, SUBENTRY_WEATHER_STATION),
        context={"source": SOURCE_USER},
    )
    duplicate = await choose_region(hass.config_entries.subentries, duplicate)
    duplicate = await save_sources(hass.config_entries.subentries, duplicate, "1629004")
    assert duplicate["type"] is FlowResultType.FORM
    assert duplicate["errors"]["base"] == "already_configured"
    assert len(config_entry.subentries) == 3
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


@pytest.mark.parametrize("failure", ["discovery", "selection", "missing", "empty"])
async def test_subentry_failure(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    config_entry: MockConfigEntry,
    failure: str,
) -> None:
    """A failed subentry flow never changes the saved station set."""
    config_entry.add_to_hass(hass)
    if failure == "discovery":
        mock_http.get(weather_url(), status=503)
    else:
        mock_http.get(
            weather_url(), payload=page([] if failure == "empty" else features)
        )
    result = await hass.config_entries.subentries.async_init(
        (config_entry.entry_id, SUBENTRY_WEATHER_STATION),
        context={"source": SOURCE_USER},
    )
    if failure in {"selection", "missing"}:
        if failure == "selection":
            mock_http.get(weather_url(("1629004",)), status=503)
        else:
            mock_http.get(weather_url(("1629004",)), payload=page([]))
        result = await choose_region(hass.config_entries.subentries, result)
        result = await save_sources(hass.config_entries.subentries, result, "1629004")
    result = await finish_progress(hass.config_entries.subentries, result)
    assert result["type"] is FlowResultType.FORM
    assert (
        result["errors"]["base"]
        == {
            "discovery": "cannot_connect",
            "selection": "cannot_connect",
            "missing": "station_missing",
            "empty": "no_stations",
        }[failure]
    )
    assert len(config_entry.subentries) == 2


async def test_concurrent_duplicate_selection(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    config_entry: MockConfigEntry,
) -> None:
    """Recheck source identity after network I/O before creating a subentry."""
    from custom_components.vegvesen.api import parse_station  # noqa: PLC0415

    config_entry.add_to_hass(hass)
    station = parse_station(features[2])

    async def selected(*_: Any) -> dict[str, Any]:
        with patch(
            "custom_components.vegvesen.api.VegvesenApiClient.async_get_weather",
            return_value={station.source_id: station},
        ):
            other = await hass.config_entries.subentries.async_init(
                (config_entry.entry_id, SUBENTRY_WEATHER_STATION),
                context={"source": SOURCE_USER},
            )
            other = await choose_region(hass.config_entries.subentries, other)
            await save_sources(hass.config_entries.subentries, other, station.source_id)
        return {station.source_id: station}

    with patch(
        "custom_components.vegvesen.api.VegvesenApiClient.async_get_weather",
        return_value={station.source_id: station},
    ):
        result = await hass.config_entries.subentries.async_init(
            (config_entry.entry_id, SUBENTRY_WEATHER_STATION),
            context={"source": SOURCE_USER},
        )
        result = await finish_progress(hass.config_entries.subentries, result)
    with patch(
        "custom_components.vegvesen.api.VegvesenApiClient.async_get_weather",
        new=AsyncMock(side_effect=selected),
    ):
        result = await choose_region(hass.config_entries.subentries, result)
        result = await save_sources(
            hass.config_entries.subentries, result, station.source_id
        )
    result = await finish_progress(hass.config_entries.subentries, result)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "already_configured"
    assert len(config_entry.subentries) == 3
    assert not mock_http.requests  # All source I/O was mocked at the client boundary.
