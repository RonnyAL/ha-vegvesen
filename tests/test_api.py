"""Verify faithful parsing and complete, bounded pagination."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import TYPE_CHECKING, Any

import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.vegvesen.api import (
    VegvesenApiClient,
    VegvesenApiError,
    VegvesenRateLimitError,
    parse_station,
)

from .helpers import page, weather_url

if TYPE_CHECKING:
    from aioresponses import aioresponses
    from homeassistant.core import HomeAssistant


@pytest.mark.parametrize("temperature", [None, 0, -39.6, -273.2, 9999])
def test_native_temperature(
    features: list[dict[str, Any]], temperature: float | None
) -> None:
    """Null, zero and unusual source values are never corrected."""
    features[0]["properties"]["AIR_TEMPERATURE"] = temperature
    station = parse_station(features[0])
    assert station.air_temperature == temperature
    assert station.longitude == features[0]["geometry"]["coordinates"][0]
    assert station.latitude == features[0]["geometry"]["coordinates"][1]
    assert station.measurement_time == datetime.fromisoformat(
        features[0]["properties"]["MEASUREMENT_TIME"]
    )


def test_identity_and_missing_values(features: list[dict[str, Any]]) -> None:
    """Leading zeroes and source identity survive feature/publication changes."""
    feature = features[0]
    feature["properties"]["REFERENCE_ID"] = "001629006"
    before = parse_station(feature)
    feature["id"] = "WeatherSimple_v2.new-row"
    feature["properties"]["PUB_ID"] += 1
    assert parse_station(feature) == before
    del feature["properties"]["AIR_TEMPERATURE"]
    feature["properties"]["MEASUREMENT_TIME"] = None
    feature["properties"]["LOCATION_DESCRIPTION"] = None
    feature["geometry"] = None
    station = parse_station(feature)
    assert station.source_id == "001629006"
    assert station.air_temperature is None
    assert station.measurement_time is None
    assert station.latitude is None
    assert station.name == "001629006"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("REFERENCE_ID", None),
        ("REFERENCE_ID", 1629006),
        ("LOCATION_DESCRIPTION", 12),
        ("ROAD_NUMBER", []),
        ("AIR_TEMPERATURE", "7.2"),
        ("AIR_TEMPERATURE", True),
        ("MEASUREMENT_TIME", "invalid"),
        ("MEASUREMENT_TIME", "2026-10-03T09:30:00"),
    ],
)
def test_malformed_feature(
    features: list[dict[str, Any]], field: str, value: Any
) -> None:
    """Schema failures are explicit rather than inferred corrections."""
    features[0]["properties"][field] = value
    with pytest.raises(VegvesenApiError):
        parse_station(features[0])


async def test_filtered_pagination(
    hass: HomeAssistant, mock_http: aioresponses, features: list[dict[str, Any]]
) -> None:
    """Follow server links and publish only the combined complete result."""
    ids = ("1629006", "1629013")
    next_url = weather_url(ids, 1)
    mock_http.get(
        weather_url(ids), payload=page(features[:1], matched=2, next_url=next_url)
    )
    mock_http.get(
        next_url, payload=page(features[1:2], matched=2, next_url=weather_url(ids, 2))
    )
    # GeoServer may advertise an additional empty terminal page.
    mock_http.get(weather_url(ids, 2), payload=page([], matched=2))
    client = VegvesenApiClient(async_get_clientsession(hass))
    assert set(await client.async_get_weather(ids)) == set(ids)
    assert len(mock_http.requests) == 3


@pytest.mark.parametrize(
    "failure",
    ["http", "timeout", "incomplete", "changed_count", "duplicate", "malformed"],
)
async def test_failed_second_page(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    failure: str,
) -> None:
    """Never return the successful first page as a complete snapshot."""
    next_url = weather_url(start_index=1)
    mock_http.get(
        weather_url(), payload=page(features[:1], matched=2, next_url=next_url)
    )
    if failure == "http":
        mock_http.get(next_url, status=503)
    elif failure == "timeout":
        mock_http.get(next_url, exception=TimeoutError())
    elif failure == "incomplete":
        mock_http.get(next_url, payload=page([], matched=2))
    elif failure == "changed_count":
        mock_http.get(next_url, payload=page(features[1:2], matched=3))
    elif failure == "duplicate":
        mock_http.get(next_url, payload=page(features[:1], matched=2))
    else:
        mock_http.get(next_url, body="{invalid", content_type="application/json")
    client = VegvesenApiClient(async_get_clientsession(hass))
    with pytest.raises(VegvesenApiError):
        await client.async_get_weather()


@pytest.mark.parametrize(
    "failure",
    [
        "cycle",
        "foreign",
        "filter_removed",
        "count",
        "no_counts",
        "extra",
        "links",
        "multiple_next",
        "empty_next",
    ],
)
async def test_invalid_pagination(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    failure: str,
) -> None:
    """Detect truncation, invalid metadata, changed queries and endless links."""
    ids = ("1629006", "1629013")
    payload = page(features[:1], matched=2, next_url=weather_url(ids, 1))
    if failure == "cycle":
        payload["links"][0]["href"] = weather_url(ids)
    elif failure == "foreign":
        payload["links"][0]["href"] = "https://example.com/weather"
    elif failure == "filter_removed":
        payload["links"][0]["href"] = weather_url(start_index=1)
    elif failure == "count":
        payload["numberReturned"] = 2
    elif failure == "no_counts":
        del payload["numberMatched"]
    elif failure == "extra":
        payload["numberMatched"] = 0
    elif failure == "links":
        payload["links"] = [None]
    elif failure == "multiple_next":
        payload["links"] *= 2
    else:
        payload["features"] = []
        payload["numberReturned"] = 0
    mock_http.get(weather_url(ids), payload=payload)
    client = VegvesenApiClient(async_get_clientsession(hass))
    with pytest.raises(VegvesenApiError):
        await client.async_get_weather(ids)
    assert len(mock_http.requests) == 1


async def test_unrequested_and_absent_station(
    hass: HomeAssistant, mock_http: aioresponses, features: list[dict[str, Any]]
) -> None:
    """An ignored filter fails; a complete empty result is legitimate absence."""
    client = VegvesenApiClient(async_get_clientsession(hass))
    mock_http.get(weather_url(("missing",)), payload=page(features[:1]))
    with pytest.raises(VegvesenApiError, match="unrequested"):
        await client.async_get_weather({"missing"})
    mock_http.get(weather_url(("missing",)), payload=page([]))
    assert await client.async_get_weather({"missing"}) == {}
    requests = len(mock_http.requests)
    assert await client.async_get_weather(set()) == {}
    assert len(mock_http.requests) == requests


@pytest.mark.parametrize(
    ("header", "expected"),
    [(None, 60), ("120", 120), ("invalid", 60), ("-1", 60), ("nan", 60), ("inf", 60)],
)
async def test_rate_limit(
    hass: HomeAssistant, mock_http: aioresponses, header: str | None, expected: int
) -> None:
    """Respect retry guidance without misclassifying a public API as auth."""
    mock_http.get(
        weather_url(), status=429, headers={"Retry-After": header} if header else {}
    )
    client = VegvesenApiClient(async_get_clientsession(hass))
    with pytest.raises(VegvesenRateLimitError) as caught:
        await client.async_get_weather()
    assert caught.value.retry_after == expected


async def test_rate_limit_http_date(
    hass: HomeAssistant, mock_http: aioresponses, freezer: Any
) -> None:
    """Parse the HTTP-date form of Retry-After."""
    freezer.move_to("2026-10-03T08:00:00Z")
    header = format_datetime(datetime(2026, 10, 3, 8, 2, tzinfo=UTC), usegmt=True)
    mock_http.get(weather_url(), status=429, headers={"Retry-After": header})
    with pytest.raises(VegvesenRateLimitError) as caught:
        await VegvesenApiClient(async_get_clientsession(hass)).async_get_weather()
    assert caught.value.retry_after == 120


async def test_cql_literal_escaping(
    hass: HomeAssistant, mock_http: aioresponses, features: list[dict[str, Any]]
) -> None:
    """Source strings remain opaque and cannot alter filter expressions."""
    feature = deepcopy(features[0])
    feature["properties"]["REFERENCE_ID"] = "001'23"
    mock_http.get(weather_url(("001'23",)), payload=page([feature]))
    result = await VegvesenApiClient(async_get_clientsession(hass)).async_get_weather(
        {"001'23"}
    )
    assert list(result) == ["001'23"]
