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


async def choose_region(
    manager: Any,
    result: dict[str, Any],
    county: str = "Trøndelag",
    municipality: str = "Orkland",
) -> dict[str, Any]:
    """Exercise native region steps before selecting a fixture source."""
    assert list(result["data_schema"].schema) == ["county"]
    assert result["last_step"] is False
    result = await manager.async_configure(result["flow_id"], {"county": county})
    assert list(result["data_schema"].schema) == ["municipality"]
    assert result["last_step"] is False
    result = await manager.async_configure(
        result["flow_id"], {"municipality": municipality}
    )
    assert result["last_step"] is True
    return result
