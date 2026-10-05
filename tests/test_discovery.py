"""Test shared catalogue caching without changing coordinator polling semantics."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from aioresponses import CallbackResult

from custom_components.vegvesen.api import VegvesenApiError
from custom_components.vegvesen.discovery import (
    CATALOGUE_TTL,
    async_get_discovery,
    parse_source_geography,
)

from .helpers import camera_url, page, weather_url

if TYPE_CHECKING:
    from aioresponses import aioresponses
    from homeassistant.core import HomeAssistant


async def test_shared_cache_and_expiry(
    hass: HomeAssistant, mock_http: aioresponses, features: list[dict[str, Any]]
) -> None:
    """Subsequent flows reuse a complete catalogue; fresh copies prevent mutation."""
    cache = async_get_discovery(hass)
    assert async_get_discovery(hass) is cache
    mock_http.get(weather_url(), payload=page(features))
    with patch("custom_components.vegvesen.discovery.monotonic", return_value=10):
        first = await cache.weather.async_get()
        second = await cache.weather.async_get()
    first.clear()
    assert len(second) == 3
    assert sum(map(len, mock_http.requests.values())) == 1
    mock_http.get(weather_url(), payload=page(features[:1]))
    with patch(
        "custom_components.vegvesen.discovery.monotonic",
        return_value=11 + CATALOGUE_TTL,
    ):
        assert len(await cache.weather.async_get()) == 1
    assert sum(map(len, mock_http.requests.values())) == 2


@pytest.mark.parametrize(
    "problem", ["http", "incomplete", "next_http", "next_incomplete", "empty"]
)
async def test_refresh_failure_recovery(
    hass: HomeAssistant,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    problem: str,
) -> None:
    """An expired or incomplete catalogue cannot masquerade as a fresh snapshot."""
    cache = async_get_discovery(hass).weather
    mock_http.get(weather_url(), payload=page(features))
    with patch("custom_components.vegvesen.discovery.monotonic", return_value=10):
        await cache.async_get()
    if problem == "http":
        mock_http.get(weather_url(), status=503)
    elif problem.startswith("next_"):
        next_url = weather_url(start_index=1)
        mock_http.get(
            weather_url(), payload=page(features[:1], matched=2, next_url=next_url)
        )
        if problem == "next_http":
            mock_http.get(next_url, status=503)
        else:
            mock_http.get(next_url, payload=page([], matched=2))
    else:
        mock_http.get(
            weather_url(), payload=page([], matched=1 if problem == "incomplete" else 0)
        )
    with patch(
        "custom_components.vegvesen.discovery.monotonic",
        return_value=11 + CATALOGUE_TTL,
    ):
        if problem == "empty":
            assert await cache.async_get() == {}
        else:
            with pytest.raises(VegvesenApiError):
                await cache.async_get()
        if problem == "empty":
            assert await cache.async_get() == {}
            cache._expires = 0
        mock_http.get(weather_url(), payload=page(features[:1]))
        assert len(await cache.async_get()) == 1


async def test_simultaneous_flows_and_cancellation(
    hass: HomeAssistant, mock_http: aioresponses, features: list[dict[str, Any]]
) -> None:
    """Cancellation releases the cache lock; concurrent flows share one retrieval."""
    started, release = asyncio.Event(), asyncio.Event()

    async def pending(*_: Any, **__: Any) -> CallbackResult:
        started.set()
        await release.wait()
        return CallbackResult(payload=page(features))

    cache = async_get_discovery(hass).weather
    mock_http.get(weather_url(), callback=pending)
    cancelled = asyncio.create_task(cache.async_get())
    await started.wait()
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    started.clear()
    mock_http.get(weather_url(), callback=pending)
    tasks = [asyncio.create_task(cache.async_get()) for _ in range(3)]
    await started.wait()
    release.set()
    results = await asyncio.gather(*tasks)
    assert all(len(result) == 3 for result in results)
    assert sum(map(len, mock_http.requests.values())) == 2


async def test_independent_families(
    hass: HomeAssistant,
    mock_http: aioresponses,
    camera_features: list[dict[str, Any]],
) -> None:
    """Weather discovery failure never blocks camera discovery or its cache."""
    mock_http.get(weather_url(), status=503)
    mock_http.get(camera_url(), payload=page(camera_features))
    discovery = async_get_discovery(hass)
    with pytest.raises(VegvesenApiError):
        await discovery.weather.async_get()
    assert len(await discovery.cameras.async_get()) == 3
    assert len(await discovery.cameras.async_get()) == 3
    assert sum(map(len, mock_http.requests.values())) == 2


@pytest.mark.parametrize("problem", ["version", "coordinate", "name", "identity"])
def test_invalid_geography_index(problem: str) -> None:
    """Malformed package metadata is rejected as a whole, without partial labels."""
    payload = {
        "version": 1,
        "sources": {
            "camera:1": {
                "latitude": 62.0,
                "longitude": 5.0,
                "county": "Møre og Romsdal",
                "municipality": "Herøy",
            }
        },
    }
    data = deepcopy(payload)
    if problem == "version":
        data["version"] = 2
    elif problem == "coordinate":
        data["sources"]["camera:1"]["latitude"] = None
    elif problem == "name":
        data["sources"]["camera:1"]["county"] = ""
    else:
        data["sources"]["other:1"] = data["sources"].pop("camera:1")
    with pytest.raises(ValueError, match="Invalid source geography"):
        parse_source_geography(data)
