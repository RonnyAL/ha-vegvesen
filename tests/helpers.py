"""Build mock pages from a captured public response."""

from typing import Any

from yarl import URL

from custom_components.vegvesen.const import CAMERA_ITEMS_URL, WEATHER_ITEMS_URL


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
    assert result["type"] == "menu"
    assert action in result["menu_options"]
    return await manager.async_configure(result["flow_id"], {"next_step_id": action})


async def choose_region(
    manager: Any,
    result: dict[str, Any],
    county: str = "Trøndelag",
    municipality: str = "Orkland",
) -> dict[str, Any]:
    """Use the overview's region actions and open the source selection form."""
    result = await menu_action(manager, result, "county")
    assert list(result["data_schema"].schema) == ["county"]
    result = await manager.async_configure(result["flow_id"], {"county": county})
    result = await menu_action(manager, result, "municipality")
    assert list(result["data_schema"].schema) == ["municipality"]
    result = await manager.async_configure(
        result["flow_id"], {"municipality": municipality}
    )
    action = next(
        action for action in result["menu_options"] if action.endswith("_sources")
    )
    return await menu_action(manager, result, action)


async def save_sources(
    manager: Any, result: dict[str, Any], *ids: str
) -> dict[str, Any]:
    """Save a draft, then explicitly confirm Add from the overview."""
    result = await manager.async_configure(result["flow_id"], {"sources": list(ids)})
    return await menu_action(manager, result, "add")
