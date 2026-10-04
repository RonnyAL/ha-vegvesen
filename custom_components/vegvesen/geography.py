"""Kartverket administrative lookups used only while selecting a source."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import aiohttp

from .const import REQUEST_TIMEOUT

if TYPE_CHECKING:
    from .api import RoadCamera, WeatherStation

GEOGRAPHY_URL = "https://api.kartverket.no/kommuneinfo/v1"
LOOKUP_CONCURRENCY = 4


class GeographyError(Exception):
    """An administrative lookup failed or returned incomplete metadata."""


@dataclass(frozen=True, slots=True)
class Municipality:
    """Official municipality identity, name and candidate search bounds."""

    number: str
    name: str
    bounds: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class County:
    """Official county identity and its municipalities."""

    number: str
    name: str
    bounds: tuple[float, float, float, float]
    municipalities: dict[str, Municipality]


def _identity(
    record: Any, prefix: str, digits: int, *, name_field: str | None = None
) -> tuple[str, str]:
    """Validate official names and string codes, retaining leading zeroes."""
    if not isinstance(record, dict):
        raise GeographyError("Expected administrative metadata")
    number = record.get(f"{prefix}nummer")
    name = record.get(name_field or f"{prefix}navn")
    if (
        not isinstance(number, str)
        or len(number) != digits
        or not number.isascii()
        or not number.isdigit()
        or not isinstance(name, str)
        or not name
    ):
        raise GeographyError("Invalid administrative name or code")
    return number, name


def _bounds(record: dict[str, Any]) -> tuple[float, float, float, float]:
    """Read an EPSG:4326 bounding box; it never proves area membership."""
    try:
        box = record["avgrensningsboks"]
        if box["type"] != "Polygon" or box["crs"]["properties"]["name"] != "EPSG:4326":
            raise GeographyError("Unexpected bounding box coordinate system")
        ring = box["coordinates"][0]
        if len(ring) < 4 or any(  # noqa: PLR2004
            len(point) != 2 or any(type(n) not in (int, float) for n in point)  # noqa: PLR2004
            for point in ring
        ):
            raise GeographyError("Invalid administrative bounding box")
        return (
            min(point[0] for point in ring),
            min(point[1] for point in ring),
            max(point[0] for point in ring),
            max(point[1] for point in ring),
        )
    except (KeyError, IndexError, TypeError) as err:
        raise GeographyError("Missing administrative bounding box") from err


def parse_counties(payload: Any) -> dict[str, County]:
    """Reject a malformed directory instead of offering partial categories."""
    if not isinstance(payload, list) or not payload:
        raise GeographyError("Missing administrative directory")
    counties: dict[str, County] = {}
    for record in payload:
        number, name = _identity(record, "fylkes", 2)
        if number in counties or not isinstance(record.get("kommuner"), list):
            raise GeographyError("Duplicate county or missing municipalities")
        municipalities: dict[str, Municipality] = {}
        for item in record["kommuner"]:
            code, label = _identity(item, "kommune", 4, name_field="kommunenavnNorsk")
            if code in municipalities or not code.startswith(number):
                raise GeographyError("Duplicate municipality or incorrect county")
            municipalities[code] = Municipality(code, label, _bounds(item))
        if not municipalities:
            raise GeographyError("Empty county municipality list")
        counties[number] = County(number, name, _bounds(record), municipalities)
    return counties


class GeographyClient:
    """Cache point results for one flow; never use geography during polling."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Use HA's shared session without assuming ownership of it."""
        self._session = session
        self._points: dict[tuple[float, float], tuple[str, str] | None] = {}

    async def _async_get(self, path: str, params: dict[str, str]) -> Any:
        """Bound requests and keep HTTP failures distinct from outside Norway."""
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.get(
                    f"{GEOGRAPHY_URL}/{path}", params=params
                ) as response:
                    if path == "punkt" and response.status == HTTPStatus.NOT_FOUND:
                        return None
                    response.raise_for_status()
                    payload = await response.json()
                    if payload is None:
                        raise GeographyError("Missing administrative response")
                    return payload
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise GeographyError("Cannot retrieve administrative metadata") from err

    async def async_get_counties(self) -> dict[str, County]:
        """Fetch current fylker/kommuner, without credentials or baked-in names."""
        return parse_counties(
            await self._async_get("fylkerkommuner", {"utkoordsys": "4326"})
        )

    async def async_get_membership(
        self, point: tuple[float, float]
    ) -> tuple[str, str] | None:
        """Look up one exact coordinate, reusing successful results and 404s."""
        if point in self._points:
            return self._points[point]
        payload = await self._async_get(
            "punkt",
            {"nord": str(point[0]), "ost": str(point[1]), "koordsys": "4326"},
        )
        result = None
        if payload is not None:
            code, _ = _identity(payload, "kommune", 4)
            county_code, _ = _identity(payload, "fylkes", 2)
            if not code.startswith(county_code):
                raise GeographyError("Inconsistent point administrative codes")
            result = county_code, code
        self._points[point] = result
        return result

    async def async_filter[T: WeatherStation | RoadCamera](
        self, sources: dict[str, T], county: County, municipality: str | None
    ) -> dict[str, T]:
        """Verify every candidate's membership; failed lookups fail the filter."""
        bounds = (
            county.municipalities[municipality].bounds
            if municipality is not None
            else county.bounds
        )
        west, south, east, north = bounds
        candidates = {
            source_id: source
            for source_id, source in sources.items()
            if source.latitude is not None
            and source.longitude is not None
            and west <= source.longitude <= east
            and south <= source.latitude <= north
        }
        points = {(source.latitude, source.longitude) for source in candidates.values()}
        semaphore = asyncio.Semaphore(LOOKUP_CONCURRENCY)

        async def lookup(point: tuple[float, float]) -> None:
            async with semaphore:
                await self.async_get_membership(point)

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with asyncio.TaskGroup() as group:
                    for point in points:
                        group.create_task(lookup(point))
        except (ExceptionGroup, TimeoutError) as err:
            raise GeographyError("Incomplete administrative lookup") from err
        return {
            source_id: source
            for source_id, source in candidates.items()
            if (area := self._points[(source.latitude, source.longitude)]) is not None
            and area[0] == county.number
            and (municipality is None or area[1] == municipality)
        }
