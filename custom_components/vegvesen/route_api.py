"""Public road routing and source road-condition forecasts."""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import aiohttp

from .api import (
    VegvesenApiClient,
    VegvesenApiError,
    VegvesenRateLimitError,
    _retry_after,
)
from .const import REQUEST_TIMEOUT
from .route_geometry import validate_lines

if TYPE_CHECKING:
    from collections.abc import Sequence

ROUTING_URL = "https://www.vegvesen.no/ws/no/vegvesen/ruteplan/routingservice_v3_0/open/routingservice/api/Route/best"
FORECAST_URL = "https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/collections/vegvar_1_0:vv_road_prognosis_V2/items"


@dataclass(frozen=True, slots=True)
class RoadRoute:
    """A routing proposal; its transient API routeId is never an entity identity."""

    name: str
    length: int | float
    geometry: dict[str, Any]


def parse_routes(payload: Any) -> list[RoadRoute]:
    """Require usable complete geometry for every offered road route."""
    if not isinstance(payload, dict) or not isinstance(payload.get("routes"), list):
        raise VegvesenApiError("Invalid routing response")
    routes = []
    for route in payload["routes"]:
        if not isinstance(route, dict) or route.get("type") != "FeatureCollection":
            raise VegvesenApiError("Invalid route collection")
        if route.get("isObstructed") is not False:
            continue
        if not isinstance(route.get("features"), list) or not route["features"]:
            raise VegvesenApiError("Missing route parts")
        lines = []
        for feature in route["features"]:
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                raise VegvesenApiError("Invalid route part")
            lines.extend(validate_lines(feature.get("geometry")))
        name = route.get("routeName")
        statistic = route.get("statistic")
        if not isinstance(name, str) or not name or not isinstance(statistic, dict):
            raise VegvesenApiError("Missing route metadata")
        length = statistic.get("totalLength")
        if type(length) not in (int, float) or not math.isfinite(length):
            raise VegvesenApiError("Missing route length")
        routes.append(
            RoadRoute(name, length, {"type": "MultiLineString", "coordinates": lines})
        )
    return routes


@dataclass(frozen=True, slots=True)
class RoadForecast:
    """An unchanged forecast for one source road segment and valid time."""

    segment_id: int
    forecast_time: datetime
    geometry: dict[str, Any] | None
    properties: dict[str, Any]

    @property
    def source_id(self) -> str:
        """Uniqueness is segment plus forecast time, including segment zero."""
        return f"{self.segment_id}:{self.forecast_time.astimezone(UTC).isoformat()}"


def parse_forecast(feature: Any) -> RoadForecast:
    """Validate structure and units; never reject an unusual measurement value."""
    if not isinstance(feature, dict) or feature.get("type") != "Feature":
        raise VegvesenApiError("Invalid forecast feature")
    props = feature.get("properties")
    if not isinstance(props, dict) or type(props.get("ROAD_SEGMENT_ID")) is not int:
        raise VegvesenApiError("Invalid forecast segment ID")
    try:
        forecast_time = datetime.fromisoformat(props["FORECAST_TIME"])
    except (KeyError, TypeError, ValueError) as err:
        raise VegvesenApiError("Invalid forecast time") from err
    if forecast_time.tzinfo is None:
        raise VegvesenApiError("Forecast time has no timezone")
    geometry = feature.get("geometry")
    if geometry is not None:
        validate_lines(geometry)
    for field in ("ROAD_CONDITION", "SLIP_RISK"):
        if props.get(field) is not None and not isinstance(props[field], str):
            raise VegvesenApiError("Invalid forecast category")
    temperature = props.get("ROAD_TEMPERATURE")
    if temperature is not None:
        if type(temperature) not in (int, float) or not math.isfinite(temperature):
            raise VegvesenApiError("Invalid forecast temperature")
        if props.get("ROAD_TEMPERATURE_UOM") != "°C":
            raise VegvesenApiError("Unexpected forecast temperature unit")
    return RoadForecast(props["ROAD_SEGMENT_ID"], forecast_time, geometry, dict(props))


class RouteApiClient:
    """Keep routing setup separate from periodic road forecasts."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Use HA's shared session without owning it."""
        self._session = session
        self._collections = VegvesenApiClient(session)

    async def async_routes(self, stops: Sequence[dict[str, float]]) -> list[RoadRoute]:
        """Calculate candidate road geometries only when users configure a route."""
        params = {
            "Stops": ";".join(f"{p['longitude']},{p['latitude']}" for p in stops),
            "InputSRS": "EPSG_4326",
            "OutputSRS": "EPSG_4326",
            "ReturnFields": "Geometry",
            "Lang": "Norwegian",
        }
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.get(
                    ROUTING_URL, params=params, allow_redirects=False
                ) as response:
                    if response.status == HTTPStatus.TOO_MANY_REQUESTS:
                        raise VegvesenRateLimitError(
                            _retry_after(response.headers.get("Retry-After"))
                        )
                    if response.status == HTTPStatus.NOT_FOUND:
                        error = await response.json()
                        code = error.get("code") if isinstance(error, dict) else None
                        if code == 9005 or (type(code) is int and 9200 <= code <= 9299):  # noqa: PLR2004
                            return []
                        raise VegvesenApiError("Routing service returned an error")
                    response.raise_for_status()
                    if response.status != HTTPStatus.OK:
                        raise VegvesenApiError("Unexpected routing response")
                    return parse_routes(await response.json())
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise VegvesenApiError("Cannot calculate road route") from err

    async def async_forecasts(
        self, bbox: str, forecast_time: datetime
    ) -> dict[str, RoadForecast]:
        """Reject partial snapshots and responses for an unrequested forecast time."""
        params = {
            "f": "application/json",
            "limit": "500",
            "bbox": bbox,
            "filter-lang": "cql2-text",
            "filter": f"FORECAST_TIME = TIMESTAMP('{forecast_time.isoformat()}')",
        }
        records = await self._collections.async_get_snapshot(
            FORECAST_URL, params, parse_forecast
        )
        if any(record.forecast_time != forecast_time for record in records.values()):
            raise VegvesenApiError("Server returned an unrequested forecast time")
        return records
