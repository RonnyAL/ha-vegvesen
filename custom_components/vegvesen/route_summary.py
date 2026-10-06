"""Summarize source categories without inventing a road-condition severity scale."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .route_coordinator import RouteSnapshot

SLIP_GRADES = ("low", "medium", "high")
CONDITION_CODES = (
    "NoNewPrecipitation",
    "WetRoadSurface",
    "IceOrFrost",
    "SnowCover",
    "DriftingSnow",
)


def category_counts(snapshot: RouteSnapshot | None, field: str) -> Counter[str | None]:
    """Count returned matched records, not road length or verified route coverage."""
    return (
        Counter(r.properties.get(field) for r in snapshot.segments)
        if snapshot
        else Counter()
    )


def highest_slip_risk(snapshot: RouteSnapshot | None) -> str | None:
    """Return the highest supplied grade, leaving unknown codes unranked."""
    counts = category_counts(snapshot, "SLIP_RISK")
    return next((grade for grade in reversed(SLIP_GRADES) if counts[grade]), None)


def category_summary(snapshot: RouteSnapshot | None, field: str) -> dict[str, Any]:
    """Keep missing and unrecognized values distinct from known category counts."""
    counts = category_counts(snapshot, field)
    known = SLIP_GRADES if field == "SLIP_RISK" else CONDITION_CODES
    return {
        "source_categories": {
            key: count for key, count in counts.items() if key is not None
        },
        "missing_segments": counts[None] + counts["ErrorOrNoData"],
        "unrecognized_segments": sum(
            count
            for key, count in counts.items()
            if key is not None and key not in (*known, "ErrorOrNoData")
        ),
    }


def forecast_summary(snapshot: RouteSnapshot) -> dict[str, Any]:
    """Small action response using the same source categories as route sensors."""
    temperatures = [
        value
        for record in snapshot.segments
        if (value := record.properties.get("ROAD_TEMPERATURE")) is not None
    ]
    return {
        "matched_segments": len(snapshot.segments),
        "road_condition": category_summary(snapshot, "ROAD_CONDITION"),
        "slipperiness": {
            **category_summary(snapshot, "SLIP_RISK"),
            "highest_known": highest_slip_risk(snapshot),
        },
        "road_temperature": {
            "minimum": min(temperatures, default=None),
            "maximum": max(temperatures, default=None),
            "unit": "°C",
            "missing_segments": len(snapshot.segments) - len(temperatures),
        },
    }
