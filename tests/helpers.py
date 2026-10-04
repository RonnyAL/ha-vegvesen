"""Build mock pages from a captured public response."""

from typing import Any

from homeassistant.data_entry_flow import FlowResultType
from yarl import URL

from custom_components.vegvesen.const import CAMERA_ITEMS_URL, WEATHER_ITEMS_URL


async def finish_progress(manager: Any, result: dict[str, Any]) -> dict[str, Any]:
    """Follow HA's native progress completion, as the frontend does."""
    while result["type"] in {
        FlowResultType.SHOW_PROGRESS,
        FlowResultType.SHOW_PROGRESS_DONE,
    }:
        await manager.hass.async_block_till_done()
        result = await manager.async_configure(result["flow_id"])
    return result


def weather_url(
    ids: tuple[str, ...] | None = None, start_index: int | None = None
) -> str:
    """Return the real endpoint with explicit query parameters."""
    params = {"f": "application/json", "limit": "500"}
    if ids is not None:
        literals = ",".join(
            "'" + value.replace("'", "''") + "'" for value in sorted(ids)
        )
        params.update(
            {"filter-lang": "cql2-text", "filter": f"REFERENCE_ID IN ({literals})"}
        )
    if start_index is not None:
        params["startIndex"] = str(start_index)
    return str(URL(WEATHER_ITEMS_URL).with_query(params))


def page(
    features: list[dict[str, Any]],
    *,
    matched: int | None = None,
    next_url: str | None = None,
) -> dict[str, Any]:
    """Retain actual feature fields while controlling pagination metadata."""
    return {
        "type": "FeatureCollection",
        "features": features,
        "numberMatched": len(features) if matched is None else matched,
        "numberReturned": len(features),
        "links": [{"rel": "next", "href": next_url}] if next_url else [],
    }


def camera_url(
    ids: tuple[str, ...] | None = None, start_index: int | None = None
) -> str:
    """Use the actual CCTV endpoint and camera identifier filter."""
    return (
        weather_url(ids, start_index)
        .replace(WEATHER_ITEMS_URL, CAMERA_ITEMS_URL)
        .replace("REFERENCE_ID", "CAMERA_ID")
    )


async def menu_action(
    manager: Any, result: dict[str, Any], action: str
) -> dict[str, Any]:
    """Choose a visible native menu action through HA's manager."""
    result = await finish_progress(manager, result)
    assert result["type"] == "menu"
    assert action in result["menu_options"]
    return await finish_progress(
        manager,
        await manager.async_configure(result["flow_id"], {"next_step_id": action}),
    )


async def choose_region(
    manager: Any,
    result: dict[str, Any],
    county: str = "Trøndelag",
    municipality: str = "Orkland",
) -> dict[str, Any]:
    """Submit the county and municipality forms to reach source selection."""
    result = await finish_progress(manager, result)
    assert result["step_id"] == "county"
    assert list(result["data_schema"].schema) == ["county"]
    result = await manager.async_configure(result["flow_id"], {"county": county})
    assert result["step_id"] == "municipality"
    assert list(result["data_schema"].schema) == ["municipality"]
    result = await manager.async_configure(
        result["flow_id"], {"municipality": municipality}
    )
    assert result["step_id"].endswith("_sources")
    return result


async def save_sources(
    manager: Any, result: dict[str, Any], *ids: str
) -> dict[str, Any]:
    """Submit the final checkbox form, validating the entire batch before save."""
    result = await manager.async_configure(result["flow_id"], {"sources": list(ids)})
    return await finish_progress(manager, result)
