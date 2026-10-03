"""Verify camera-only setup and camera subentry selection/rejection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from aioresponses import CallbackResult
from homeassistant.config_entries import SOURCE_USER, ConfigSubentry
from homeassistant.data_entry_flow import FlowResultType

from custom_components.vegvesen.const import CONF_CAMERA_ID, DOMAIN, SUBENTRY_CAMERA

from .helpers import camera_url, choose_region, page, save_sources

if TYPE_CHECKING:
    from aioresponses import aioresponses
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_camera_only_parent(
    hass: HomeAssistant,
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
) -> None:
    """Camera discovery/setup never depends on the weather catalogue."""
    mock_http.get(camera_url(), payload=page(camera_features))
    mock_http.get(camera_url(("3000047_2",)), payload=page(camera_features[:1]))
    with patch("custom_components.vegvesen.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.MENU
        assert set(result["menu_options"]) == {"weather_station", "camera"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": SUBENTRY_CAMERA}
        )
        result = await choose_region(
            hass.config_entries.flow, result, "Møre og Romsdal", "Herøy"
        )
        options = result["data_schema"].schema["sources"].config["options"]
        assert any(
            "Rundebrua — Runde (3000047_2)" in option["label"] for option in options
        )
        result = await save_sources(hass.config_entries.flow, result, "3000047_2")
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.unique_id == "public_service"
    assert len(entry.subentries) == 1
    source = next(iter(entry.subentries.values()))
    assert source.unique_id == "camera:3000047_2"
    assert source.data == {CONF_CAMERA_ID: "3000047_2"}


@pytest.mark.parametrize("kind", ["parent", "subentry"])
@pytest.mark.parametrize(
    "failure", ["discovery", "incomplete", "empty", "missing", "selection"]
)
async def test_camera_flow_failure(
    hass: HomeAssistant,
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
    camera_entry: MockConfigEntry,
    kind: str,
    failure: str,
) -> None:
    """Bad discovery/selection does not save partial or missing camera choices."""
    if failure == "discovery":
        mock_http.get(camera_url(), status=503)
    else:
        mock_http.get(
            camera_url(),
            payload=page(
                [] if failure in {"incomplete", "empty"} else camera_features,
                matched=1 if failure == "incomplete" else None,
            ),
        )
    if kind == "parent":
        manager = hass.config_entries.flow
        result = await manager.async_init(DOMAIN, context={"source": SOURCE_USER})
        result = await manager.async_configure(
            result["flow_id"], {"next_step_id": SUBENTRY_CAMERA}
        )
    else:
        camera_entry.add_to_hass(hass)
        manager = hass.config_entries.subentries
        result = await manager.async_init(
            (camera_entry.entry_id, SUBENTRY_CAMERA), context={"source": SOURCE_USER}
        )
    if failure in {"selection", "missing"}:
        if failure == "selection":
            mock_http.get(camera_url(("1429014_1",)), status=503)
        else:
            mock_http.get(camera_url(("1429014_1",)), payload=page([]))
        result = await choose_region(manager, result, "Vestland", "Kinn")
        result = await save_sources(manager, result, "1429014_1")
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == {
        "empty": "no_cameras",
        "missing": "camera_missing",
    }.get(failure, "cannot_connect")
    assert len(camera_entry.subentries) == 2


async def test_camera_add_and_duplicate(
    hass: HomeAssistant,
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
    camera_entry: MockConfigEntry,
) -> None:
    """Allow selecting a source-reported faulted camera, but never duplicate its ID."""
    camera_entry.add_to_hass(hass)
    mock_http.get(camera_url(), payload=page(camera_features), repeat=True)
    mock_http.get(camera_url(("1429014_1",)), payload=page(camera_features[2:]))
    manager = hass.config_entries.subentries
    for expected in (FlowResultType.CREATE_ENTRY, FlowResultType.FORM):
        result = await manager.async_init(
            (camera_entry.entry_id, SUBENTRY_CAMERA), context={"source": SOURCE_USER}
        )
        result = await choose_region(manager, result, "Vestland", "Kinn")
        result = await save_sources(manager, result, "1429014_1")
        assert result["type"] is expected
    assert result["errors"]["base"] == "already_configured"
    assert len(camera_entry.subentries) == 3


async def test_camera_concurrent_duplicate(
    hass: HomeAssistant,
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
    camera_entry: MockConfigEntry,
) -> None:
    """A concurrent selection during validation cannot duplicate physical ownership."""
    camera_entry.add_to_hass(hass)
    mock_http.get(camera_url(), payload=page(camera_features))

    async def competing_selection(*_: Any, **__: Any) -> CallbackResult:
        hass.config_entries.async_add_subentry(
            camera_entry,
            ConfigSubentry(
                subentry_type=SUBENTRY_CAMERA,
                unique_id="camera:1429014_1",
                title="Grytadalen",
                data={CONF_CAMERA_ID: "1429014_1"},
            ),
        )
        return CallbackResult(payload=page(camera_features[2:]))

    mock_http.get(camera_url(("1429014_1",)), callback=competing_selection)
    manager = hass.config_entries.subentries
    result = await manager.async_init(
        (camera_entry.entry_id, SUBENTRY_CAMERA), context={"source": SOURCE_USER}
    )
    result = await choose_region(manager, result, "Vestland", "Kinn")
    result = await save_sources(manager, result, "1429014_1")
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "already_configured"
    assert len(camera_entry.subentries) == 3
