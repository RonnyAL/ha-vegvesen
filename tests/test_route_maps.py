"""Route images, signed previews, provider limits and coordinator lifecycle."""

from __future__ import annotations

import asyncio
import json
import math
import re
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.setup import async_setup_component
from PIL import Image, ImageColor, ImageDraw
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vegvesen.const import DOMAIN
from custom_components.vegvesen.map_tiles import TILE_TTL, USER_AGENT, MapTiles
from custom_components.vegvesen.route_map import (
    HEIGHT,
    PADDING,
    ROUTE_COLOR,
    WIDTH,
    MapContent,
    _draw_basemap,
    make_viewport,
    render_map,
)
from custom_components.vegvesen.route_map_view import MapDocument, async_get_route_maps

from .helpers import menu_action

if TYPE_CHECKING:
    from aioresponses import aioresponses
    from homeassistant.core import HomeAssistant

TILES = re.compile(r"https://tile\.openstreetmap\.org/\d+/\d+/\d+\.png")


@pytest.fixture
def tile_png() -> bytes:
    """Generate a tiny valid, neutral test tile without fetching a basemap."""
    output = BytesIO()
    Image.new("RGB", (256, 256), "#eeeeee").save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def labels() -> dict[str, str]:
    """Use the same translated raster labels as the packaged renderer."""
    path = Path(__file__).parents[1] / "custom_components/vegvesen/map_labels.json"
    all_labels = json.loads(path.read_text())
    assert all_labels["en"].keys() == all_labels["nb"].keys()
    return all_labels["nb"]


def test_render_disconnected_lines(labels: dict[str, str], tile_png: bytes) -> None:
    """Never draw a invented bridge across disconnected source route parts."""
    content = MapContent(
        "Trondheim → Orkanger",
        {
            "type": "MultiLineString",
            "coordinates": [[[10, 63], [10.01, 63]], [[10.03, 63], [10.04, 63]]],
        },
    )
    view = make_viewport(content)
    tiles = dict.fromkeys(view.tiles().values(), tile_png)
    png, complete = render_map(view, tiles, labels)
    assert complete
    with Image.open(BytesIO(png)) as image:
        assert image.size == (WIDTH, HEIGHT)
        x, y = view.point(10.005, 63)
        assert image.getpixel((round(x), round(y))) == ImageColor.getrgb(ROUTE_COLOR)
        x, y = view.point(10.02, 63)
        assert image.getpixel((round(x), round(y))) == (238, 238, 238)


@pytest.mark.parametrize(
    "coordinates",
    [[[179.9, 60], [-179.9, 60]], [[10, 89], [10.01, 89]], [[10, 63], [10, 63]]],
)
def test_geographic_limits(coordinates: list, labels: dict[str, str]) -> None:
    """Bound tile requests, wrap longitude, and retain polar/zero-length geometry."""
    content = MapContent("Test", {"type": "LineString", "coordinates": coordinates})
    view = make_viewport(content)
    assert len(view.tiles()) <= 20
    for point in coordinates:
        x, y = view.point(*point)
        assert 0 <= x <= WIDTH
        assert 0 <= y <= HEIGHT
    png, _ = render_map(view, {}, labels)
    assert png.startswith(b"\x89PNG")


@pytest.mark.parametrize(
    "coordinates",
    [
        [[10, 63], [10.04, 63]],
        [[10, 63], [10, 64]],
        [[10, 63], [12, 64]],
        [[179.9, 60], [-179.9, 60]],
    ],
)
def test_route_fills_viewport_without_cropping(coordinates: list) -> None:
    """The limiting axis fits exactly, retaining padding and bounded tile work."""
    view = make_viewport(
        MapContent("Test", {"type": "LineString", "coordinates": coordinates})
    )
    points = [view.point(*point) for point in coordinates]
    xs, ys = zip(*points, strict=True)
    assert min(xs) >= PADDING - 1e-6
    assert max(xs) <= WIDTH - PADDING + 1e-6
    assert min(ys) >= PADDING - 1e-6
    assert max(ys) <= HEIGHT - PADDING + 1e-6
    assert max(
        (max(xs) - min(xs)) / (WIDTH - 2 * PADDING),
        (max(ys) - min(ys)) / (HEIGHT - 2 * PADDING),
    ) == pytest.approx(1)
    assert len(view.tiles()) <= 20
    assert {key[0] for key in view.tiles().values()} == {math.floor(view.zoom)}


def test_fractional_fit_keeps_basemap_aligned() -> None:
    """An integer tile boundary lands at the same pixel as its road coordinate."""
    view = make_viewport(
        MapContent(
            "Test", {"type": "LineString", "coordinates": [[10, 63], [10.04, 63]]}
        )
    )
    assert not view.zoom.is_integer()
    tile = Image.new("RGB", (256, 256), "#eeeeee")
    ImageDraw.Draw(tile).rectangle((0, 0, 7, 255), fill="red")
    output = BytesIO()
    tile.save(output, format="PNG")
    basemap, complete = _draw_basemap(
        view, dict.fromkeys(view.tiles().values(), output.getvalue())
    )
    assert complete
    # x / 2**z marks a tile's western longitude, independently of the renderer.
    boundaries = (
        view.point(tile_x / 2**view.tile_zoom * 360 - 180, 63)
        for tile_x in {x for x, _ in view.tiles()}
    )
    x, y = next(point for point in boundaries if 20 < point[0] < WIDTH - 20)
    assert basemap.getpixel((round(x + 3 * view.tile_scale), round(y))) == (255, 0, 0)
    assert basemap.getpixel((round(x - 3 * view.tile_scale), round(y))) == (
        238,
        238,
        238,
    )


def test_overview_strokes_thinner_than_close_view(labels: dict[str, str]) -> None:
    """Actual painted route strokes scale with zoom instead of staying 10px wide."""
    widths = []
    for span in (1, 0.01):
        content = MapContent(
            "Test", {"type": "LineString", "coordinates": [[10, 63], [10 + span, 63]]}
        )
        png, _ = render_map(make_viewport(content), {}, labels)
        with Image.open(BytesIO(png)) as image:
            widths.append(
                sum(
                    image.getpixel((WIDTH // 2, y)) == ImageColor.getrgb(ROUTE_COLOR)
                    for y in range(HEIGHT // 2 - 20, HEIGHT // 2 + 20)
                )
            )
    assert 1 <= widths[0] < 6
    assert widths[1] > widths[0]


def test_marker_ink_centered(labels: dict[str, str], tile_png: bytes) -> None:
    """Center the actual A/B letter bounds, independently of font ascenders."""
    content = MapContent(
        "Test", {"type": "LineString", "coordinates": [[10, 63], [10.04, 63]]}
    )
    view = make_viewport(content)
    png, _ = render_map(view, dict.fromkeys(view.tiles().values(), tile_png), labels)
    with Image.open(BytesIO(png)) as image:
        for point in content.geometry["coordinates"]:
            x, y = view.point(*point)
            pixels = [
                (px, py)
                for px in range(round(x) - 8, round(x) + 9)
                for py in range(round(y) - 8, round(y) + 9)
                if (px - x) ** 2 + (py - y) ** 2 < 64
                and min(image.getpixel((px, py))) > 210
            ]
            xs, ys = zip(*pixels, strict=True)
            assert abs((min(xs) + max(xs)) / 2 - x) <= 1
            assert abs((min(ys) + max(ys)) / 2 - y) <= 1


async def test_tiles_cached_coalesced_bounded(
    hass: HomeAssistant, mock_http: aioresponses, tile_png: bytes
) -> None:
    """Concurrent views share requests; refresh after seven days, with bounded LRU."""
    mock_http.get(TILES, body=tile_png, content_type="image/png", repeat=True)
    tiles = MapTiles(hass)
    keys = {(8, 130, 85), (8, 131, 85)}
    with patch("custom_components.vegvesen.map_tiles.time.monotonic", return_value=100):
        results = await asyncio.gather(tiles.async_tiles(keys), tiles.async_tiles(keys))
        assert results[0] == results[1] == dict.fromkeys(keys, tile_png)
    assert sum(len(calls) for calls in mock_http.requests.values()) == 2
    request = next(iter(mock_http.requests.values()))[0]
    assert request.kwargs["headers"]["User-Agent"] == USER_AGENT
    with patch(
        "custom_components.vegvesen.map_tiles.time.monotonic",
        return_value=100 + TILE_TTL,
    ):
        assert await tiles.async_tiles(keys) == results[0]
    assert sum(len(calls) for calls in mock_http.requests.values()) == 4
    with patch("custom_components.vegvesen.map_tiles.MAX_CACHE_BYTES", len(tile_png)):
        assert await tiles.async_tiles({(8, 132, 85)})
        assert tiles._size <= len(tile_png)
        assert len(tiles._cache) == 1


@pytest.mark.parametrize(
    "failure", ["429", "503", "timeout", "mime", "huge", "corrupt", "redirect"]
)
async def test_tile_failures_and_recovery(
    hass: HomeAssistant, mock_http: aioresponses, tile_png: bytes, failure: str
) -> None:
    """Invalid tiles fail softly and cannot trigger a retry storm or redirects."""
    options = {
        "429": {"status": 429, "headers": {"Retry-After": "120"}},
        "503": {"status": 503},
        "timeout": {"exception": TimeoutError()},
        "mime": {"body": tile_png, "content_type": "text/html"},
        "huge": {
            "body": tile_png,
            "content_type": "image/png",
            "headers": {"Content-Length": str(1024 * 1024)},
        },
        "corrupt": {"body": b"\x89PNG\r\n\x1a\n", "content_type": "image/png"},
        "redirect": {"status": 302, "headers": {"Location": "http://localhost/"}},
    }
    mock_http.get(TILES, **options[failure])
    tiles = MapTiles(hass)
    with patch("custom_components.vegvesen.map_tiles.time.monotonic", return_value=100):
        assert await tiles.async_tiles({(8, 130, 85)}) == {}
        assert await tiles.async_tiles({(8, 131, 85)}) == {}
        assert sum(len(calls) for calls in mock_http.requests.values()) == 1
    mock_http.get(TILES, body=tile_png, content_type="image/png")
    with patch("custom_components.vegvesen.map_tiles.time.monotonic", return_value=221):
        assert await tiles.async_tiles({(8, 130, 85)}) == {(8, 130, 85): tile_png}


async def test_signed_preview_auth(
    hass: HomeAssistant,
    hass_client_no_auth: Any,
    route_data: dict[str, Any],
    freezer: Any,
) -> None:
    """HA rejects unsigned/tampered/expired URLs; revocation is immediate."""
    assert await async_setup_component(hass, "http", {})
    maps = async_get_route_maps(hass)
    url = maps.async_preview("test-flow", MapContent("Test", route_data["geometry"]))
    client = await hass_client_no_auth()
    with patch.object(MapDocument, "async_image", return_value=b"test-png"):
        response = await client.get(url)
        assert response.status == 200
        assert await response.read() == b"test-png"
        assert response.headers["Cache-Control"] == "private, no-store"
        assert (await client.get(url.split("?")[0])).status in {401, 403}
        assert (await client.get(url.replace("test-flow", "other-flow"))).status in {
            401,
            403,
        }
        maps.async_preview("test-flow", MapContent("Changed", route_data["geometry"]))
        assert (await client.get(url)).status == 404
        url = maps.async_preview(
            "test-flow", MapContent("Test", route_data["geometry"])
        )
        freezer.tick(timedelta(minutes=31))
        assert (await client.get(url)).status in {401, 403}


@pytest.mark.parametrize("finish", ["cancel", "save"])
async def test_flow_preview_cleanup(
    hass: HomeAssistant, route_data: dict[str, Any], finish: str
) -> None:
    """Reconfiguration uses saved geometry and removes previews on exit."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="public_service",
        subentries_data=[
            {
                "subentry_type": "route",
                "title": "Public example",
                "data": route_data,
                "unique_id": "route:example-route",
            }
        ],
    )
    entry.add_to_hass(hass)
    manager = hass.config_entries.subentries
    result = await manager.async_init(
        (entry.entry_id, "route"),
        context={
            "source": SOURCE_RECONFIGURE,
            "subentry_id": next(iter(entry.subentries)),
        },
    )
    flow_id = result["flow_id"]
    maps = async_get_route_maps(hass)
    original = maps.previews[flow_id]
    assert original.content.geometry == route_data["geometry"]
    result = await menu_action(manager, result, "route_choice")
    result = await manager.async_configure(flow_id, {"route": "0"})
    assert maps.previews[flow_id].revision != original.revision
    if finish == "cancel":
        manager.async_abort(flow_id)
    else:
        await menu_action(manager, result, "route_save")
    assert flow_id not in maps.previews
    assert next(iter(entry.subentries.values())).data == route_data


async def test_preview_revoked_during_render(
    hass: HomeAssistant, hass_client_no_auth: Any, route_data: dict[str, Any]
) -> None:
    """Canceling a flow cannot finish serving its private image after revocation."""
    assert await async_setup_component(hass, "http", {})
    maps = async_get_route_maps(hass)
    url = maps.async_preview("test-flow", MapContent("Test", route_data["geometry"]))
    client = await hass_client_no_auth()
    started, finish = asyncio.Event(), asyncio.Event()

    async def delayed_image(_maps: Any) -> bytes:
        started.set()
        await finish.wait()
        return b"image"

    with patch.object(
        maps.previews["test-flow"], "async_image", side_effect=delayed_image
    ):
        task = asyncio.create_task(client.get(url))
        await started.wait()
        maps.previews.pop("test-flow")
        finish.set()
        assert (await task).status == 404


async def test_map_timeout_fallback_and_retry(
    hass: HomeAssistant, route_data: dict[str, Any], tile_png: bytes
) -> None:
    """A background failure yields a usable route and retries on a later view."""
    assert await async_setup_component(hass, "http", {})
    maps = async_get_route_maps(hass)
    document = MapDocument(MapContent("Public example", route_data["geometry"]))
    with patch.object(maps.tiles, "async_tiles", side_effect=TimeoutError()):
        fallback = await document.async_image(maps)
    assert fallback.startswith(b"\x89PNG")
    with patch.object(maps.tiles, "async_tiles") as request:
        assert await document.async_image(maps) == fallback
        request.assert_not_called()
        request.return_value = dict.fromkeys(
            make_viewport(document.content).tiles().values(), tile_png
        )
        document._expires = 0
        assert await document.async_image(maps) != fallback
        request.assert_awaited_once()
    assert await maps.async_labels("untranslated-language") == await maps.async_labels(
        "en"
    )
