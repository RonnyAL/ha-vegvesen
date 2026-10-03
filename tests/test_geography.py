"""Verify administrative parsing, exact membership, caching and failures."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from aioresponses import CallbackResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from yarl import URL

from custom_components.vegvesen.api import parse_camera, parse_station
from custom_components.vegvesen.geography import (
    GEOGRAPHY_URL,
    LOOKUP_CONCURRENCY,
    GeographyClient,
    GeographyError,
    parse_counties,
)

if TYPE_CHECKING:
    from aioresponses import aioresponses
    from homeassistant.core import HomeAssistant


def point_url(latitude: float, longitude: float) -> str:
    """Match the API's explicitly specified WGS84 coordinate order."""
    return str(
        URL(f"{GEOGRAPHY_URL}/punkt").with_query(
            {"nord": str(latitude), "ost": str(longitude), "koordsys": "4326"}
        )
    )


def point_payload(county: str, municipality: str) -> dict[str, str]:
    """Build an official-shaped result with explicit administrative identities."""
    return {
        "fylkesnummer": county,
        "fylkesnavn": "Source county",
        "kommunenummer": municipality,
        "kommunenavn": "Source municipality",
    }


def test_directory(counties_payload: list[dict[str, Any]]) -> None:
    """Parse all real counties and municipalities, retaining official names."""
    counties = parse_counties(counties_payload)
    assert len(counties) == 15
    assert counties["03"].name == "Oslo"
    assert counties["50"].municipalities["5059"].name == "Orkland"
    assert counties["15"].municipalities["1515"].name == "Herøy"


@pytest.mark.parametrize(
    "problem",
    ["empty", "type", "code", "name", "duplicate", "municipality", "crs", "box"],
)
def test_bad_directory(counties_payload: list[dict[str, Any]], problem: str) -> None:
    """Malformed categories never become an apparently complete directory."""
    payload = deepcopy(counties_payload[:1])
    if problem == "empty":
        payload = []
    elif problem == "type":
        payload = [None]
    elif problem == "code":
        payload[0]["fylkesnummer"] = 55
    elif problem == "name":
        payload[0]["fylkesnavn"] = None
    elif problem == "duplicate":
        payload.append(payload[0])
    elif problem == "municipality":
        payload[0]["kommuner"][0]["kommunenummer"] = "0301"
    elif problem == "crs":
        payload[0]["avgrensningsboks"]["crs"]["properties"]["name"] = "EPSG:4258"
    else:
        del payload[0]["avgrensningsboks"]["coordinates"]
    with pytest.raises(GeographyError):
        parse_counties(payload)


async def test_point_and_cache(
    hass: HomeAssistant,
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
    counties_payload: list[dict[str, Any]],
) -> None:
    """Use real Herøy membership and reuse duplicate direction coordinates."""
    client = GeographyClient(async_get_clientsession(hass))
    camera = parse_camera(camera_features[0])
    duplicate = deepcopy(camera_features[0])
    duplicate["properties"]["CAMERA_ID"] = "second_direction"
    other = parse_camera(duplicate)
    sources = {camera.source_id: camera, other.source_id: other}
    payload = json.loads(
        (Path(__file__).parent / "fixtures/geography_point.json").read_text()
    )
    mock_http.get(point_url(camera.latitude, camera.longitude), payload=payload)
    county = parse_counties(counties_payload)["15"]
    assert await client.async_filter(sources, county, "1515") == sources
    requests = len(mock_http.requests)
    assert await client.async_filter(sources, county, None) == sources
    assert len(mock_http.requests) == requests == 1


@pytest.mark.parametrize("result", ["other_county", "other_municipality", "outside"])
async def test_bounds_are_only_candidates(
    hass: HomeAssistant,
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
    counties_payload: list[dict[str, Any]],
    result: str,
) -> None:
    """Bounding-box overlap must never incorrectly classify a source."""
    camera = parse_camera(camera_features[0])
    url = point_url(camera.latitude, camera.longitude)
    if result == "outside":
        mock_http.get(url, status=404)
    else:
        mock_http.get(
            url,
            payload=point_payload(
                "46" if result == "other_county" else "15",
                "4601" if result == "other_county" else "1507",
            ),
        )
    client = GeographyClient(async_get_clientsession(hass))
    assert (
        await client.async_filter(
            {camera.source_id: camera}, parse_counties(counties_payload)["15"], "1515"
        )
        == {}
    )


@pytest.mark.parametrize("problem", ["http", "null", "inconsistent", "timeout"])
async def test_filter_is_atomic_and_recovers(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    counties_payload: list[dict[str, Any]],
    problem: str,
) -> None:
    """A single failed candidate rejects the filter; a later attempt recovers."""
    stations = [parse_station(feature) for feature in (features[0], features[2])]
    sources = {station.source_id: station for station in stations}
    urls = [point_url(station.latitude, station.longitude) for station in stations]
    mock_http.get(urls[0], payload=point_payload("50", "5059"), repeat=True)
    if problem == "http":
        mock_http.get(urls[1], status=503)
    elif problem == "timeout":
        mock_http.get(urls[1], exception=TimeoutError())
    else:
        mock_http.get(
            urls[1],
            payload=None if problem == "null" else point_payload("15", "5059"),
        )
    client = GeographyClient(async_get_clientsession(hass))
    county = parse_counties(counties_payload)["50"]
    with pytest.raises(GeographyError, match="Incomplete"):
        await client.async_filter(sources, county, "5059")
    mock_http.get(urls[1], payload=point_payload("50", "5059"))
    assert await client.async_filter(sources, county, "5059") == sources


async def test_bounded_concurrency_and_cancellation(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    counties_payload: list[dict[str, Any]],
) -> None:
    """Cancelling discovery stops its lookups and leaves no background requests."""
    sources = {}
    started = asyncio.Event()
    active = 0
    cancelled = 0

    async def pending(*_: Any, **__: Any) -> CallbackResult:
        nonlocal active, cancelled
        active += 1
        if active == LOOKUP_CONCURRENCY:
            started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled += 1
            raise
        return CallbackResult(payload=point_payload("50", "5059"))

    for index in range(10):
        feature = deepcopy(features[0])
        feature["properties"]["REFERENCE_ID"] = str(index)
        feature["geometry"]["coordinates"][0] += index / 1000
        station = parse_station(feature)
        sources[station.source_id] = station
        mock_http.get(point_url(station.latitude, station.longitude), callback=pending)
    client = GeographyClient(async_get_clientsession(hass))
    task = asyncio.create_task(
        client.async_filter(sources, parse_counties(counties_payload)["50"], None)
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    assert active == LOOKUP_CONCURRENCY
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled == LOOKUP_CONCURRENCY
