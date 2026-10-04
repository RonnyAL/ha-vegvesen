"""Native authenticated preview images and a shared on-demand map renderer."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.http.auth import async_sign_path
from homeassistant.core import callback

from .map_tiles import MapTiles
from .route_map import MapContent, make_viewport, render_map

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

DATA_MAPS = "vegvesen_route_maps"
PREVIEW_URL = "/api/vegvesen/route_preview/{flow_id}/{revision}"


class MapDocument:
    """Lazily render one immutable snapshot, coalescing concurrent viewers."""

    def __init__(self, content: MapContent) -> None:
        """Retain geometry in memory only; never put it in an entity's state."""
        self.content = content
        self.revision = uuid4().hex
        self._lock = asyncio.Lock()
        self._image: bytes | None = None
        self._expires = 0.0
        self._language: str | None = None

    async def async_image(self, maps: RouteMaps) -> bytes:
        """Render the proposal only when viewed."""
        async with self._lock:
            language = maps.hass.config.language
            if (
                self._image
                and self._expires > time.monotonic()
                and self._language == language
            ):
                return self._image
            view = await maps.hass.async_add_executor_job(make_viewport, self.content)
            tiles = {}
            try:
                async with asyncio.timeout(7):
                    tiles = await maps.tiles.async_tiles(set(view.tiles().values()))
            except TimeoutError:
                pass
            labels = await maps.async_labels(language)
            self._image, complete = await maps.hass.async_add_executor_job(
                render_map, view, tiles, labels
            )
            self._expires = time.monotonic() + (3600 if complete else 60)
            self._language = language
            return self._image


class RouteMaps:
    """Share tile requests across flow previews."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Register one authenticated HA view for the lifetime of the integration."""
        self.hass = hass
        self.tiles = MapTiles(hass)
        self.previews: dict[str, MapDocument] = {}
        self._labels: dict[str, dict[str, str]] | None = None
        hass.http.register_view(RoutePreviewView(self))

    async def async_labels(self, language: str) -> dict[str, str]:
        """Raster text follows HA's configured language, with an English fallback."""
        if self._labels is None:
            text = await self.hass.async_add_executor_job(
                Path(__file__).with_name("map_labels.json").read_text
            )
            self._labels = json.loads(text)
        return self._labels.get(language, self._labels["en"])

    @callback
    def async_preview(self, flow_id: str, content: MapContent) -> str:
        """Replace the flow's image and sign its exact path using HA authentication."""
        document = self.previews[flow_id] = MapDocument(content)
        return async_sign_path(
            self.hass,
            PREVIEW_URL.format(flow_id=flow_id, revision=document.revision),
            timedelta(minutes=30),
        )


class RoutePreviewView(HomeAssistantView):
    """Serve only a live flow's current preview, through HA's signed-path auth."""

    url = PREVIEW_URL
    name = "api:vegvesen:route_preview"

    def __init__(self, maps: RouteMaps) -> None:
        """Keep previews owned by the flow, not by a public static directory."""
        self.maps = maps

    async def get(
        self, _request: web.Request, flow_id: str, revision: str
    ) -> web.Response:
        """Expired, canceled or superseded proposals cannot be retrieved."""
        document = self.maps.previews.get(flow_id)
        if document is None or document.revision != revision:
            raise web.HTTPNotFound
        image = await document.async_image(self.maps)
        if self.maps.previews.get(flow_id) is not document:
            raise web.HTTPNotFound
        return web.Response(
            body=image,
            content_type="image/png",
            headers={"Cache-Control": "private, no-store"},
        )


@callback
def async_get_route_maps(hass: HomeAssistant) -> RouteMaps:
    """Create the renderer lazily, without network requests or background tasks."""
    if DATA_MAPS not in hass.data:
        hass.data[DATA_MAPS] = RouteMaps(hass)
    return hass.data[DATA_MAPS]
