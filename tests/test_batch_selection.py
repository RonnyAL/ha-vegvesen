"""Batch selection is validated completely before any source is persisted."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigSubentry
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vegvesen.const import DOMAIN

from .helpers import (
    camera_url,
    choose_region,
    finish_progress,
    page,
    save_sources,
    weather_url,
)
from .test_selection import start_flow

if TYPE_CHECKING:
    from aioresponses import aioresponses
    from homeassistant.core import HomeAssistant


@pytest.mark.parametrize("family", ["weather_station", "camera"])
@pytest.mark.parametrize("kind", ["parent", "subentry"])
@pytest.mark.parametrize("outcome", ["success", "missing", "pagination", "duplicate"])
async def test_batch_validation(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    camera_features: list[dict[str, Any]],
    family: str,
    kind: str,
    outcome: str,
) -> None:
    """A selected batch creates all physical sources or leaves the entry untouched."""
    weather = family == "weather_station"
    records = features if weather else camera_features
    key, field = (
        ("REFERENCE_ID", "station_id") if weather else ("CAMERA_ID", "camera_id")
    )
    ids = [record["properties"][key] for record in records]
    endpoint = weather_url if weather else camera_url
    entry = MockConfigEntry(domain=DOMAIN, unique_id="public_service", data={})
    mock_http.get(endpoint(), payload=page(records))
    with (
        patch(
            "custom_components.vegvesen.discovery._read_source_geography",
            return_value={},
        ),
        patch("custom_components.vegvesen.async_setup_entry", return_value=True),
    ):
        manager, result = await start_flow(hass, family, kind, entry)
        result = await choose_region(manager, result, "unknown", "unknown")
        if outcome == "duplicate" and kind == "subentry":
            hass.config_entries.async_add_subentry(
                entry,
                ConfigSubentry(
                    subentry_type=family,
                    unique_id=f"{family}:{ids[0]}",
                    title="Existing source",
                    data={field: ids[0]},
                ),
            )
        elif outcome == "pagination":
            mock_http.get(
                endpoint(tuple(ids)),
                payload=page(records[:1], matched=3, next_url=endpoint(tuple(ids), 1)),
            )
            mock_http.get(endpoint(tuple(ids), 1), status=503)
        else:
            mock_http.get(
                endpoint(tuple(ids)),
                payload=page(records[:1] if outcome == "missing" else records),
            )
        result = await manager.async_configure(
            result["flow_id"], {"sources": ids + ids[:1]}
        )
        result = await finish_progress(manager, result)
        await hass.async_block_till_done()
    if outcome in {"missing", "pagination"} or (
        outcome == "duplicate" and kind == "subentry"
    ):
        assert result["type"] is FlowResultType.FORM
        assert result["errors"]["base"] == (
            "already_configured"
            if outcome == "duplicate"
            else "cannot_connect"
            if outcome == "pagination"
            else "station_missing"
            if weather
            else "camera_missing"
        )
        assert len(entry.subentries) == (1 if outcome == "duplicate" else 0)
        if kind == "parent":
            assert not hass.config_entries.async_entries(DOMAIN)
        if outcome == "duplicate":
            assert len(mock_http.requests) == 1
    else:
        assert result["type"] is FlowResultType.CREATE_ENTRY
        saved = result["result"] if kind == "parent" else entry
        assert {source.unique_id for source in saved.subentries.values()} == {
            f"{family}:{source_id}" for source_id in ids
        }
        assert {source.data[field] for source in saved.subentries.values()} == set(ids)
        assert len(saved.subentries) == 3


async def test_loaded_entry_batch_reload(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
) -> None:
    """A batch reloads once, creates all entities and shuts down its old resources."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id="public_service", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    old_weather = entry.runtime_data.weather
    ids = [record["properties"]["REFERENCE_ID"] for record in features]
    mock_http.get(weather_url(), payload=page(features))
    # One validation request and exactly one coordinator refresh for the batch.
    mock_http.get(weather_url(tuple(ids)), payload=page(features), repeat=2)
    manager = hass.config_entries.subentries
    with patch(
        "custom_components.vegvesen.discovery._read_source_geography", return_value={}
    ):
        result = await manager.async_init(
            (entry.entry_id, "weather_station"), context={"source": SOURCE_USER}
        )
        result = await choose_region(manager, result, "unknown", "unknown")
        with patch.object(
            hass.config_entries, "async_reload", wraps=hass.config_entries.async_reload
        ) as reload_entry:
            result = await save_sources(manager, result, *ids)
            await hass.async_block_till_done()
            assert reload_entry.call_count == 1
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert old_weather._shutdown_requested
    assert entry.runtime_data.weather.station_ids == set(ids)
    assert len(hass.states.async_all("sensor")) == 6
    assert entry.runtime_data.weather.last_update_success
    coordinator = entry.runtime_data.weather
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert coordinator._shutdown_requested


async def test_selection_arrives_during_reload(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
) -> None:
    """An addition during setup I/O is included even before listeners reattach."""
    from aioresponses import CallbackResult  # noqa: PLC0415

    entry = MockConfigEntry(domain=DOMAIN, unique_id="public_service", data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)

    def add(index: int) -> None:
        source_id = features[index]["properties"]["REFERENCE_ID"]
        hass.config_entries.async_add_subentry(
            entry,
            ConfigSubentry(
                subentry_type="weather_station",
                unique_id=f"weather_station:{source_id}",
                title=source_id,
                data={"station_id": source_id},
            ),
        )

    async def during_refresh(*_: Any, **__: Any) -> CallbackResult:
        add(1)
        return CallbackResult(payload=page(features[:1]))

    mock_http.get(weather_url(("1629006",)), callback=during_refresh)
    mock_http.get(weather_url(("1629006", "1629013")), payload=page(features[:2]))
    add(0)
    await hass.async_block_till_done()
    assert entry.runtime_data.weather.station_ids == {"1629006", "1629013"}
    assert entry.runtime_data.weather.last_update_success
    assert len(hass.states.async_all("sensor")) == 4


async def test_overlapping_batches_are_rechecked(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
) -> None:
    """An overlapping flow cannot partially save after another wins during I/O."""
    from aioresponses import CallbackResult  # noqa: PLC0415

    entry = MockConfigEntry(domain=DOMAIN, unique_id="public_service", data={})
    entry.add_to_hass(hass)
    manager = hass.config_entries.subentries
    ids = [record["properties"]["REFERENCE_ID"] for record in features]
    mock_http.get(weather_url(), payload=page(features))
    with patch(
        "custom_components.vegvesen.discovery._read_source_geography", return_value={}
    ):
        first = await manager.async_init(
            (entry.entry_id, "weather_station"), context={"source": SOURCE_USER}
        )
        first = await choose_region(manager, first, "unknown", "unknown")
        second = await manager.async_init(
            (entry.entry_id, "weather_station"), context={"source": SOURCE_USER}
        )
        second = await choose_region(manager, second, "unknown", "unknown")
    mock_http.get(weather_url(tuple(ids[1:])), payload=page(features[1:]))

    async def other_completes(*_: Any, **__: Any) -> CallbackResult:
        result = await save_sources(manager, second, *ids[1:])
        assert result["type"] is FlowResultType.CREATE_ENTRY
        return CallbackResult(payload=page(features[:2]))

    mock_http.get(weather_url(tuple(ids[:2])), callback=other_completes)
    result = await save_sources(manager, first, *ids[:2])
    assert result["errors"]["base"] == "already_configured"
    assert {source.data["station_id"] for source in entry.subentries.values()} == set(
        ids[1:]
    )
    # The losing draft can be edited and completed without restarting the flow.
    mock_http.get(weather_url((ids[0],)), payload=page(features[:1]))
    result = await save_sources(manager, result, ids[0])
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(entry.subentries) == 3
