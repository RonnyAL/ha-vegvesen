"""Metric route corridors; all geometry work runs outside HA's event loop."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pyproj import Transformer
from shapely.geometry import MultiLineString, shape
from shapely.ops import transform

from .api import VegvesenApiError

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True, slots=True)
class RouteCorridor:
    """A route-owned corridor and its WGS84 envelope for server-side filtering."""

    geometry: BaseGeometry
    bbox: str
    project: Transformer

    def intersects(self, geometry: dict[str, Any] | None) -> bool:
        """Include intersecting segments, not every road in the bounding rectangle."""
        return geometry is not None and self.geometry.intersects(
            transform(self.project.transform, shape(geometry))
        )


def validate_lines(geometry: Any) -> list[list[list[float]]]:
    """Accept finite geographic line geometry without joining disconnected parts."""
    if not isinstance(geometry, dict):
        raise VegvesenApiError("Missing road geometry")
    coordinates = geometry.get("coordinates")
    if geometry.get("type") == "LineString":
        coordinates = [coordinates]
    elif geometry.get("type") != "MultiLineString":
        raise VegvesenApiError("Expected road line geometry")
    if not isinstance(coordinates, list) or not coordinates:
        raise VegvesenApiError("Empty road geometry")
    for line in coordinates:
        if not isinstance(line, list) or len(line) < 2:  # noqa: PLR2004
            raise VegvesenApiError("Invalid road line")
        for point in line:
            if (
                not isinstance(point, list)
                or len(point) < 2  # noqa: PLR2004
                or any(
                    type(value) not in (int, float) or not math.isfinite(value)
                    for value in point[:2]
                )
                or not -180 <= point[0] <= 180  # noqa: PLR2004
                or not -90 <= point[1] <= 90  # noqa: PLR2004
            ):
                raise VegvesenApiError("Invalid geographic coordinate")
    return [[point[:2] for point in line] for line in coordinates]


def make_corridor(geometry: dict[str, Any], radius: float) -> RouteCorridor:
    """Buffer the saved route in its local metric projection and bound the query."""
    if type(radius) not in (int, float) or not math.isfinite(radius) or radius <= 0:
        raise VegvesenApiError("Invalid route corridor width")
    lines = MultiLineString(validate_lines(geometry))
    center = lines.centroid
    crs = f"+proj=aeqd +lat_0={center.y} +lon_0={center.x} +datum=WGS84 +units=m"
    project = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    reverse = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    corridor = transform(project.transform, lines).buffer(radius)
    geographic = transform(reverse.transform, corridor)
    if not geographic.is_valid or not all(math.isfinite(v) for v in geographic.bounds):
        raise VegvesenApiError("Cannot construct route corridor")
    # Round outwards so the server envelope cannot truncate the local corridor.
    west, south, east, north = geographic.bounds
    bounds = [
        math.floor(west * 1e6) / 1e6,
        math.floor(south * 1e6) / 1e6,
        math.ceil(east * 1e6) / 1e6,
        math.ceil(north * 1e6) / 1e6,
    ]
    return RouteCorridor(corridor, ",".join(str(v) for v in bounds), project)
