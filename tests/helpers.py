"""Build mock pages from a captured public response."""

from typing import Any

from yarl import URL

from custom_components.vegvesen.const import CAMERA_ITEMS_URL, WEATHER_ITEMS_URL
from custom_components.vegvesen.selection import ALL, CONF_COUNTY


async def browse_all(manager: Any, result: dict[str, Any]) -> dict[str, Any]:
    """Select the nationwide escape hatch before testing source submission."""
    if (
        "station_id" in result["data_schema"].schema
        or "camera_id" in result["data_schema"].schema
    ):
        return result
    return await manager.async_configure(result["flow_id"], {CONF_COUNTY: ALL})


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
