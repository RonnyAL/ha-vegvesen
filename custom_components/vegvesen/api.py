"""Read Statens vegvesen's public OGC collections and camera JPEGs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from http import HTTPStatus
from time import monotonic
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import aiohttp

from .const import (
    CAMERA_ITEMS_URL,
    IMAGE_REQUEST_TIMEOUT,
    REQUEST_TIMEOUT,
    WEATHER_ITEMS_URL,
)

MAX_PAGES = 1000

if TYPE_CHECKING:
    from collections.abc import Callable, Collection


class VegvesenApiError(Exception):
    """A failed request, malformed response or incomplete snapshot."""


class VegvesenRateLimitError(VegvesenApiError):
    """A server-requested pause before the next refresh."""

    def __init__(self, retry_after: float) -> None:
        """Store the delay in seconds."""
        super().__init__("Statens vegvesen rate limit")
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class WeatherStation:
    """Source identity, discovery metadata and supported observations."""

    source_id: str
    name: str
    road_number: str | None
    latitude: float | None
    longitude: float | None
    air_temperature: int | float | None
    measurement_time: datetime | None

    @property
    def label(self) -> str:
        """Return a readable label with the exact source identifier."""
        return f"{self.name} ({self.source_id})"


@dataclass(frozen=True, slots=True)
class RoadCamera:
    """Source metadata; publication times are not image capture times."""

    source_id: str
    name: str
    orientation: str | None
    road_number: str | None
    latitude: float | None
    longitude: float | None
    image_url: str | None
    image_format: str | None
    service_level: int | None
    status_service_level: int | None
    availability: str | None
    publication_time: datetime | None
    last_update_time: datetime | None

    @property
    def label(self) -> str:
        """Include direction and the entire source ID in manual selection."""
        direction = f" — {self.orientation}" if self.orientation else ""
        return f"{self.name}{direction} ({self.source_id})"

    @property
    def can_fetch_image(self) -> bool:
        """Use the documented available status and supported still format."""
        return (
            bool(self.image_url)
            and self.image_format == "jpeg"
            and self.service_level == 1
            and self.status_service_level == 1
            and self.availability == "videoOrImagesAvailable"
        )


def _timestamp(value: Any) -> datetime | None:
    """Require offset-aware source times; null remains null."""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as err:
        raise VegvesenApiError("Invalid source timestamp") from err
    if parsed.tzinfo is None:
        raise VegvesenApiError("Source timestamp has no timezone")
    return parsed


def parse_camera(feature: Any) -> RoadCamera:
    """Parse CCTV fields without using publication/row IDs for identity."""
    if not isinstance(feature, dict) or feature.get("type") != "Feature":
        raise VegvesenApiError("Expected a GeoJSON Feature")
    props = feature.get("properties")
    if not isinstance(props, dict):
        raise VegvesenApiError("Missing camera properties")
    source_id = props.get("CAMERA_ID")
    if not isinstance(source_id, str) or not source_id:
        raise VegvesenApiError("Missing camera source identifier")
    for key in (
        "DESCRIPTION",
        "ORIENTATION_DESCRIPTION",
        "ROAD_NUMBER",
        "STILL_IMAGE_URL",
        "STILL_IMAGE_FORMAT",
        "STATUS_STILL_IMAGE_AVAILABILITY",
    ):
        if (value := props.get(key)) is not None and not isinstance(value, str):
            raise VegvesenApiError(f"Expected {key} to be a string or null")
    for key in ("STILL_IMAGE_SERVICE_LEVEL", "STATUS_STILL_IMAGE_SERVICE_LEVEL"):
        if (value := props.get(key)) is not None and type(value) is not int:
            raise VegvesenApiError(f"Expected {key} to be an integer or null")
    latitude = longitude = None
    if (geometry := feature.get("geometry")) is not None:
        if not isinstance(geometry, dict) or geometry.get("type") != "Point":
            raise VegvesenApiError("Expected camera point geometry or null")
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 2:  # noqa: PLR2004
            raise VegvesenApiError("Invalid camera point coordinates")
        longitude, latitude = map(_number, coordinates[:2])
    return RoadCamera(
        source_id=source_id,
        name=props.get("DESCRIPTION") or source_id,
        orientation=props.get("ORIENTATION_DESCRIPTION"),
        road_number=props.get("ROAD_NUMBER"),
        latitude=latitude,
        longitude=longitude,
        image_url=props.get("STILL_IMAGE_URL"),
        image_format=props.get("STILL_IMAGE_FORMAT"),
        service_level=props.get("STILL_IMAGE_SERVICE_LEVEL"),
        status_service_level=props.get("STATUS_STILL_IMAGE_SERVICE_LEVEL"),
        availability=props.get("STATUS_STILL_IMAGE_AVAILABILITY"),
        publication_time=_timestamp(props.get("PUBLICATION_TIME")),
        last_update_time=_timestamp(props.get("LAST_UPDATE_TIME")),
    )


def _number(value: Any) -> int | float | None:
    """Accept source numbers and null without altering their values."""
    if value is not None and type(value) not in (int, float):
        raise VegvesenApiError("Expected a number or null")
    return value


def parse_station(feature: Any) -> WeatherStation:
    """Parse a feature; identity never comes from the GeoServer feature ID."""
    if not isinstance(feature, dict) or feature.get("type") != "Feature":
        raise VegvesenApiError("Expected a GeoJSON Feature")
    props = feature.get("properties")
    if not isinstance(props, dict):
        raise VegvesenApiError("Missing feature properties")
    source_id = props.get("REFERENCE_ID")
    if not isinstance(source_id, str) or not source_id:
        raise VegvesenApiError("Missing station source identifier")
    name, road_number = props.get("LOCATION_DESCRIPTION"), props.get("ROAD_NUMBER")
    if any(
        value is not None and not isinstance(value, str)
        for value in (name, road_number)
    ):
        raise VegvesenApiError("Expected station metadata strings or null")

    measurement_time = None
    if (raw_time := props.get("MEASUREMENT_TIME")) is not None:
        try:
            measurement_time = datetime.fromisoformat(raw_time)
        except (TypeError, ValueError) as err:
            raise VegvesenApiError("Invalid measurement timestamp") from err
        if measurement_time.tzinfo is None:
            raise VegvesenApiError("Measurement timestamp has no timezone")

    latitude = longitude = None
    if (geometry := feature.get("geometry")) is not None:
        if not isinstance(geometry, dict) or geometry.get("type") != "Point":
            raise VegvesenApiError("Expected point geometry or null")
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 2:  # noqa: PLR2004
            raise VegvesenApiError("Invalid point coordinates")
        longitude, latitude = map(_number, coordinates[:2])

    return WeatherStation(
        source_id=source_id,
        name=name or source_id,
        road_number=road_number,
        latitude=latitude,
        longitude=longitude,
        air_temperature=_number(props.get("AIR_TEMPERATURE")),
        measurement_time=measurement_time,
    )


def retry_after_seconds(value: str | None) -> float:
    """Parse both standard forms of Retry-After; fall back to one minute."""
    if value is not None:
        try:
            seconds = float(value)
        except ValueError:
            try:
                seconds = (
                    parsedate_to_datetime(value) - datetime.now(UTC)
                ).total_seconds()
            except (TypeError, ValueError, OverflowError):
                return 60
        if 0 <= seconds < float("inf"):
            return seconds
    return 60


class VegvesenApiClient:
    """Use HA's shared session; expose only complete collection snapshots."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialize without credentials or a geographic boundary."""
        self._session = session
        self._retry_at: dict[str, float] = {}

    def check_cooldown(self, endpoint: str) -> None:
        """Reject early requests locally, including setup and manual refreshes."""
        if (remaining := self._retry_at.get(endpoint, 0) - monotonic()) > 0:
            raise VegvesenRateLimitError(remaining)
        self._retry_at.pop(endpoint, None)

    def rate_limit(self, endpoint: str, header: str | None) -> VegvesenRateLimitError:
        """Retain a server cooldown without creating another polling timer."""
        delay = retry_after_seconds(header)
        self._retry_at[endpoint] = max(
            self._retry_at.get(endpoint, 0), monotonic() + delay
        )
        return VegvesenRateLimitError(delay)

    async def async_get_weather(
        self, source_ids: Collection[str] | None = None
    ) -> dict[str, WeatherStation]:
        """Enumerate stations or query selected IDs, validating every page."""
        return await self._async_get_collection(
            WEATHER_ITEMS_URL, "REFERENCE_ID", parse_station, source_ids
        )

    async def async_get_cameras(
        self, source_ids: Collection[str] | None = None
    ) -> dict[str, RoadCamera]:
        """Enumerate CCTV records or retrieve selected IDs atomically."""
        return await self._async_get_collection(
            CAMERA_ITEMS_URL, "CAMERA_ID", parse_camera, source_ids
        )

    async def async_get_image(self, url: str) -> bytes:
        """Retrieve one source JPEG with a bounded request and no disk cache."""
        target = urlsplit(url)
        if (
            target.scheme != "https"
            or target.netloc != "kamera.atlas.vegvesen.no"
            or not target.path.startswith("/api/images/")
            or target.fragment
        ):
            raise VegvesenApiError("Unsupported camera image endpoint")
        self.check_cooldown(url)
        try:
            async with asyncio.timeout(IMAGE_REQUEST_TIMEOUT):
                async with self._session.get(
                    url, headers={"Accept": "image/jpeg"}, allow_redirects=False
                ) as response:
                    if response.status == HTTPStatus.TOO_MANY_REQUESTS:
                        raise self.rate_limit(url, response.headers.get("Retry-After"))
                    response.raise_for_status()
                    if (
                        response.status != HTTPStatus.OK
                        or response.content_type != "image/jpeg"
                    ):
                        raise VegvesenApiError("Camera did not return a JPEG response")
                    body = await response.read()
                    if not body.startswith(b"\xff\xd8\xff") or not body.endswith(
                        b"\xff\xd9"
                    ):
                        raise VegvesenApiError("Empty or truncated camera JPEG")
                    return body
        except (aiohttp.ClientError, TimeoutError) as err:
            raise VegvesenApiError(f"Cannot fetch camera image: {err}") from err

    async def _async_get_collection[T: WeatherStation | RoadCamera](
        self,
        endpoint: str,
        id_field: str,
        parser: Callable[[Any], T],
        source_ids: Collection[str] | None,
    ) -> dict[str, T]:
        """Share strict pagination between the two concrete source collections."""
        if source_ids is not None and not source_ids:
            return {}
        params = {"f": "application/json", "limit": "500"}
        if source_ids is not None:
            literals = ",".join(
                "'" + source_id.replace("'", "''") + "'"
                for source_id in sorted(set(source_ids))
            )
            params.update(
                {"filter-lang": "cql2-text", "filter": f"{id_field} IN ({literals})"}
            )

        stations = await self.async_get_snapshot(endpoint, params, parser)
        if source_ids is not None and not stations.keys() <= set(source_ids):
            raise VegvesenApiError("Server returned unrequested source IDs")
        return stations

    async def async_get_snapshot[T](
        self, endpoint: str, params: dict[str, str], parser: Callable[[Any], T]
    ) -> dict[str, T]:
        """Read a complete paginated snapshot with an immutable server query."""
        stations: dict[str, T] = {}
        visited: set[str] = set()
        expected: int | None = None
        url: str | None = endpoint
        # One timeout bounds the entire snapshot, including all pages.
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                while url is not None:
                    self.check_cooldown(endpoint)
                    async with self._session.get(
                        url,
                        params=params if not visited else None,
                        headers={"Accept": "application/json"},
                    ) as response:
                        if response.status == HTTPStatus.TOO_MANY_REQUESTS:
                            raise self.rate_limit(
                                endpoint, response.headers.get("Retry-After")
                            )
                        response.raise_for_status()
                        page = await response.json()
                        current_url = str(response.url)
                    if current_url in visited:
                        raise VegvesenApiError("Pagination cycle")
                    visited.add(current_url)
                    if len(visited) > MAX_PAGES:
                        raise VegvesenApiError("Too many pagination pages")
                    expected, url = self._consume_page(
                        page, stations, expected, current_url, params, endpoint, parser
                    )
                    if url in visited:
                        raise VegvesenApiError("Pagination cycle")
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise VegvesenApiError(f"Cannot fetch collection snapshot: {err}") from err

        if len(stations) != expected:
            raise VegvesenApiError("Incomplete collection snapshot")
        return stations

    @staticmethod
    def _consume_page[T](  # noqa: PLR0913
        page: Any,
        stations: dict[str, T],
        expected: int | None,
        current_url: str,
        params: dict[str, str],
        endpoint_url: str,
        parser: Callable[[Any], T],
    ) -> tuple[int, str | None]:
        """Validate counts, identities and continuation before accepting a page."""
        if not isinstance(page, dict) or page.get("type") != "FeatureCollection":
            raise VegvesenApiError("Expected a GeoJSON FeatureCollection")
        features = page.get("features")
        matched, returned = page.get("numberMatched"), page.get("numberReturned")
        if (
            not isinstance(features, list)
            or type(matched) is not int
            or matched < 0
            or type(returned) is not int
            or returned != len(features)
        ):
            raise VegvesenApiError("Invalid pagination counts")
        if expected is not None and expected != matched:
            raise VegvesenApiError("Snapshot count changed during pagination")
        for feature in features:
            station = parser(feature)
            if station.source_id in stations:
                raise VegvesenApiError("Duplicate source ID in collection snapshot")
            stations[station.source_id] = station
        if len(stations) > matched:
            raise VegvesenApiError("Snapshot contains more records than advertised")

        links = page.get("links", [])
        if not isinstance(links, list) or any(
            not isinstance(link, dict) for link in links
        ):
            raise VegvesenApiError("Invalid pagination links")
        next_links = [link for link in links if link.get("rel") == "next"]
        if len(next_links) > 1:
            raise VegvesenApiError("Ambiguous pagination links")
        if not next_links:
            return matched, None
        href = next_links[0].get("href")
        if not isinstance(href, str) or not href or not features:
            raise VegvesenApiError("Invalid pagination continuation")
        url = urljoin(current_url, href)
        target, endpoint = urlsplit(url), urlsplit(endpoint_url)
        query = parse_qs(target.query)
        if (
            target.scheme != endpoint.scheme
            or target.netloc != endpoint.netloc
            or unquote(target.path) != endpoint.path
            or target.fragment
            or any(query.get(key) != [value] for key, value in params.items())
        ):
            raise VegvesenApiError("Pagination link changed endpoint or query")
        return matched, url
