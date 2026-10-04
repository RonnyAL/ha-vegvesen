"""Fixtures with all HTTP requests mocked and external sockets disabled."""

from __future__ import annotations

import json
from functools import partial
from inspect import signature
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import Mock, patch

import pytest
from aiohttp import ClientResponse
from aioresponses import aioresponses
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vegvesen.const import (
    CONF_CAMERA_ID,
    CONF_STATION_ID,
    DOMAIN,
    NAME,
    SUBENTRY_CAMERA,
    SUBENTRY_WEATHER_STATION,
)
from custom_components.vegvesen.geography import GEOGRAPHY_URL
from custom_components.vegvesen.route_api import parse_routes

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture(autouse=True)
def _custom_integrations(enable_custom_integrations: None) -> None:
    """Enable the repository integration, without configuring a real HA host."""


@pytest.fixture
def features() -> list[dict[str, Any]]:
    """Load unchanged source features, fresh for each test."""
    fixture = Path(__file__).parent / "fixtures" / "weather_sample.json"
    return json.loads(fixture.read_text())["features"]


@pytest.fixture
def camera_features() -> list[dict[str, Any]]:
    """Load public available and faulted cameras, unchanged between tests."""
    fixture = Path(__file__).parent / "fixtures" / "camera_sample.json"
    return json.loads(fixture.read_text())["features"]


@pytest.fixture
def counties_payload() -> list[dict[str, Any]]:
    """Load the complete unchanged public administrative directory."""
    fixture = Path(__file__).parent / "fixtures" / "geography_counties.json"
    return json.loads(fixture.read_text())


@pytest.fixture
def jpeg() -> bytes:
    """Use an actual public still as the mocked JPEG payload."""
    return (Path(__file__).parent / "fixtures" / "camera.jpg").read_bytes()


@pytest.fixture
def camera_entry(camera_features: list[dict[str, Any]]) -> MockConfigEntry:
    """Configure two camera subentries under the public-service parent."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        unique_id="public_service",
        subentries_data=[
            {
                "subentry_type": SUBENTRY_CAMERA,
                "unique_id": f"camera:{feature['properties']['CAMERA_ID']}",
                "title": feature["properties"]["DESCRIPTION"],
                "data": {CONF_CAMERA_ID: feature["properties"]["CAMERA_ID"]},
            }
            for feature in camera_features[:2]
        ],
    )


@pytest.fixture
def mock_http(counties_payload: list[dict[str, Any]]) -> Generator[aioresponses]:
    """Mock aiohttp at the request boundary, including pagination URLs."""
    # aiohttp 3.14 requires an argument omitted by aioresponses 0.7.9.
    # Older HA's aiohttp does not accept it; keep both real dependency pins.
    arguments = (
        {"stream_writer": Mock(output_size=0)}
        if "stream_writer" in signature(ClientResponse).parameters
        else {}
    )
    with (
        patch(
            "aioresponses.core.ClientResponse",
            partial(ClientResponse, **arguments),
        ),
        aioresponses() as responses,
    ):
        responses.get(
            f"{GEOGRAPHY_URL}/fylkerkommuner?utkoordsys=4326",
            # A compact subset avoids aioresponses' fake-protocol buffer limit.
            payload=[
                county
                for county in counties_payload
                if county["fylkesnummer"] in {"15", "46", "50"}
            ],
            repeat=True,
        )
        yield responses


@pytest.fixture
def config_entry(features: list[dict[str, Any]]) -> MockConfigEntry:
    """Configure two source stations under one parent."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        unique_id="public_service",
        subentries_data=[
            {
                "subentry_type": SUBENTRY_WEATHER_STATION,
                "unique_id": f"weather_station:{feature['properties']['REFERENCE_ID']}",
                "title": feature["properties"]["LOCATION_DESCRIPTION"],
                "data": {CONF_STATION_ID: feature["properties"]["REFERENCE_ID"]},
            }
            for feature in features[:2]
        ],
    )


@pytest.fixture
def routing() -> dict[str, Any]:
    """Use a public town-centre route, unrelated to personal locations."""
    return json.loads(
        (Path(__file__).parent / "fixtures/route_sample.json").read_text()
    )


@pytest.fixture
def forecasts() -> list[dict[str, Any]]:
    """Use source fields captured from a complete public forecast snapshot."""
    return json.loads(
        (Path(__file__).parent / "fixtures/road_forecast_sample.json").read_text()
    )["features"]


@pytest.fixture
def route_data(routing: dict[str, Any]) -> dict[str, Any]:
    """Define one independent route with a stable local ID."""
    route = parse_routes(routing)[0]
    return {
        "route_id": "example-route",
        "name": "Public example",
        "start": {"latitude": 63.43, "longitude": 10.395},
        "end": {"latitude": 63.305, "longitude": 9.846},
        "corridor_m": 100,
        "forecast_hours": 1,
        "geometry": route.geometry,
        "road_name": route.name,
        "length_m": route.length,
    }
