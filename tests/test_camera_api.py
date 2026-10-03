"""Verify CCTV identity, source status, pagination, and image transport."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.vegvesen.api import (
    VegvesenApiClient,
    VegvesenApiError,
    VegvesenRateLimitError,
    parse_camera,
)

from .helpers import camera_url, page

if TYPE_CHECKING:
    from aioresponses import aioresponses
    from homeassistant.core import HomeAssistant


def test_camera_identity_and_metadata(camera_features: list[dict[str, Any]]) -> None:
    """Direction suffixes and leading zeroes are physical source identity."""
    feature = camera_features[0]
    feature["properties"]["CAMERA_ID"] = "03000047_2"
    before = parse_camera(feature)
    feature["id"] = "CctvSimple_v2.republished-row"
    feature["properties"]["PUB_ID"] += 1
    assert parse_camera(feature) == before
    assert before.source_id == "03000047_2"
    assert before.label == "Rundebrua — Runde (03000047_2)"
    assert before.longitude == feature["geometry"]["coordinates"][0]
    assert before.last_update_time == datetime.fromisoformat(
        feature["properties"]["LAST_UPDATE_TIME"]
    )
    assert before.can_fetch_image
    assert not parse_camera(camera_features[2]).can_fetch_image


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("STILL_IMAGE_SERVICE_LEVEL", 0),
        ("STATUS_STILL_IMAGE_SERVICE_LEVEL", 0),
        ("STATUS_STILL_IMAGE_AVAILABILITY", None),
        ("STATUS_STILL_IMAGE_AVAILABILITY", "futureUnknownStatus"),
        ("STILL_IMAGE_URL", None),
        ("STILL_IMAGE_FORMAT", "png"),
    ],
)
def test_unavailable_or_unsupported_source(
    camera_features: list[dict[str, Any]], field: str, value: Any
) -> None:
    """Do not invent availability for null/unknown source status or unsupported data."""
    feature = camera_features[0]
    feature["properties"][field] = value
    camera = parse_camera(feature)
    assert not camera.can_fetch_image
    assert camera.service_level == feature["properties"]["STILL_IMAGE_SERVICE_LEVEL"]
    assert (
        camera.availability == feature["properties"]["STATUS_STILL_IMAGE_AVAILABILITY"]
    )


def test_missing_camera_metadata(camera_features: list[dict[str, Any]]) -> None:
    """Optional discovery/timestamp fields can be absent without fabricated values."""
    feature = camera_features[0]
    feature["geometry"] = None
    feature["properties"] = {"CAMERA_ID": "001_2"}
    camera = parse_camera(feature)
    assert camera.name == "001_2"
    assert camera.latitude is None
    assert camera.publication_time is None
    assert camera.availability is None
    assert not camera.can_fetch_image


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("CAMERA_ID", None),
        ("CAMERA_ID", 12),
        ("DESCRIPTION", []),
        ("STILL_IMAGE_SERVICE_LEVEL", True),
        ("STATUS_STILL_IMAGE_SERVICE_LEVEL", "1"),
        ("PUBLICATION_TIME", "invalid"),
        ("LAST_UPDATE_TIME", "2026-10-03T10:30:00"),
    ],
)
def test_malformed_camera(
    camera_features: list[dict[str, Any]], field: str, value: Any
) -> None:
    """Invalid source schema fails explicitly instead of applying a correction."""
    camera_features[0]["properties"][field] = value
    with pytest.raises(VegvesenApiError):
        parse_camera(camera_features[0])


async def test_camera_pagination(
    hass: HomeAssistant,
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
) -> None:
    """Filter using CAMERA_ID and accept a complete chain with an empty last page."""
    ids = ("3000047_2", "3000063_1")
    mock_http.get(
        camera_url(ids),
        payload=page(camera_features[:1], matched=2, next_url=camera_url(ids, 1)),
    )
    mock_http.get(
        camera_url(ids, 1),
        payload=page(camera_features[1:2], matched=2, next_url=camera_url(ids, 2)),
    )
    mock_http.get(camera_url(ids, 2), payload=page([], matched=2))
    result = await VegvesenApiClient(async_get_clientsession(hass)).async_get_cameras(
        ids
    )
    assert set(result) == set(ids)
    assert len(mock_http.requests) == 3


@pytest.mark.parametrize("failure", ["request", "incomplete", "duplicate", "filter"])
async def test_camera_incomplete_snapshot(
    hass: HomeAssistant,
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
    failure: str,
) -> None:
    """Never accept a partial CCTV catalogue as the selected camera snapshot."""
    ids = ("3000047_2", "3000063_1")
    mock_http.get(
        camera_url(ids),
        payload=page(camera_features[:1], matched=2, next_url=camera_url(ids, 1)),
    )
    if failure == "request":
        mock_http.get(camera_url(ids, 1), status=503)
    else:
        selected = {
            "incomplete": [],
            "duplicate": camera_features[:1],
            "filter": camera_features[2:],
        }[failure]
        mock_http.get(camera_url(ids, 1), payload=page(selected, matched=2))
    with pytest.raises(VegvesenApiError):
        await VegvesenApiClient(async_get_clientsession(hass)).async_get_cameras(ids)


async def test_jpeg_retrieval(
    hass: HomeAssistant,
    mock_http: aioresponses,
    jpeg: bytes,
) -> None:
    """Return the actual JPEG bytes without manufacturing a capture timestamp."""
    url = "https://kamera.atlas.vegvesen.no/api/images/3000047_2"
    mock_http.get(url, body=jpeg, content_type="image/jpeg")
    assert (
        await VegvesenApiClient(async_get_clientsession(hass)).async_get_image(url)
        == jpeg
    )


@pytest.mark.parametrize(
    "failure", ["request", "timeout", "html", "empty", "truncated", "redirect"]
)
async def test_image_failures(
    hass: HomeAssistant,
    mock_http: aioresponses,
    jpeg: bytes,
    failure: str,
) -> None:
    """Bad transport responses do not become usable cached stills."""
    url = "https://kamera.atlas.vegvesen.no/api/images/3000047_2"
    if failure == "request":
        mock_http.get(url, status=503)
    elif failure == "timeout":
        mock_http.get(url, exception=TimeoutError())
    elif failure == "redirect":
        mock_http.get(url, status=302, headers={"Location": "https://example.invalid"})
    else:
        mock_http.get(
            url,
            body={"html": "<html>error</html>", "empty": b"", "truncated": jpeg[:-2]}[
                failure
            ],
            content_type="image/jpeg",
        )
    with pytest.raises(VegvesenApiError):
        await VegvesenApiClient(async_get_clientsession(hass)).async_get_image(url)


async def test_image_rate_limit(hass: HomeAssistant, mock_http: aioresponses) -> None:
    """Keep Retry-After available to the per-camera backoff policy."""
    url = "https://kamera.atlas.vegvesen.no/api/images/3000047_2"
    mock_http.get(url, status=429, headers={"Retry-After": "180"})
    with pytest.raises(VegvesenRateLimitError) as error:
        await VegvesenApiClient(async_get_clientsession(hass)).async_get_image(url)
    assert error.value.retry_after == 180
