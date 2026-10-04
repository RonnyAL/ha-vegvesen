"""On-demand OSM raster tiles, independent of the forecast API and HA internals."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from http import HTTPStatus
from io import BytesIO
from typing import TYPE_CHECKING

from aiohttp import ClientError, ClientTimeout
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from PIL import Image, UnidentifiedImageError

from .api import retry_after_seconds

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
USER_AGENT = "ha-vegvesen (+https://github.com/RonnyAL/ha-vegvesen)"
TILE_TTL = 7 * 24 * 60 * 60
MAX_TILE_BYTES = 512 * 1024
MAX_CACHE_BYTES = 16 * 1024 * 1024
type TileKey = tuple[int, int, int]


def valid_tile(data: bytes) -> bool:
    """Validate PNG dimensions before decoding, and reject broken compressed data."""
    if (
        not data.startswith(b"\x89PNG\r\n\x1a\n")
        or data[16:24] != b"\x00\x00\x01\x00" * 2
    ):
        return False
    try:
        with Image.open(BytesIO(data)) as tile:
            tile.load()
    except (UnidentifiedImageError, OSError, ValueError):
        return False
    return True


class MapTiles:
    """Cache only viewed tiles for seven days, with bounded memory and concurrency."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Use HA's shared session without changing its headers or lifecycle."""
        self._hass = hass
        self._session = async_get_clientsession(hass)
        self._cache: OrderedDict[TileKey, tuple[float, bytes]] = OrderedDict()
        self._size = 0
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(4)
        self._retry_at = 0.0

    async def async_tiles(self, keys: set[TileKey]) -> dict[TileKey, bytes]:
        """Coalesce concurrent images; never fetch outside the requested viewport."""
        async with self._lock:
            values = await asyncio.gather(*(self._async_tile(key) for key in keys))
            return {
                key: value for key, value in zip(keys, values, strict=True) if value
            }

    async def _async_tile(self, key: TileKey) -> bytes | None:
        async with self._semaphore:
            now = time.monotonic()
            cached = self._cache.get(key)
            if cached and cached[0] > now:
                self._cache.move_to_end(key)
                return cached[1]
            if self._retry_at > now:
                return cached[1] if cached else None
            if (result := await self._async_fetch(key)) is None:
                return cached[1] if cached else None
            if cached:
                self._size -= len(self._cache.pop(key)[1])
            self._cache[key] = (now + TILE_TTL, result)
            self._size += len(result)
            while self._size > MAX_CACHE_BYTES:
                self._size -= len(self._cache.popitem(last=False)[1][1])
            return result

    async def _async_fetch(self, key: TileKey) -> bytes | None:
        z, x, y = key
        try:
            async with self._session.get(
                TILE_URL.format(z=z, x=x, y=y),
                headers={"User-Agent": USER_AGENT},
                timeout=ClientTimeout(total=2),
                allow_redirects=False,
            ) as response:
                if response.status != HTTPStatus.OK:
                    self._backoff(response.headers.get("Retry-After"))
                    return None
                if (
                    response.content_type != "image/png"
                    or (response.content_length or 0) > MAX_TILE_BYTES
                ):
                    self._backoff(None)
                    return None
                data = bytearray()
                async for chunk in response.content.iter_chunked(16384):
                    data.extend(chunk)
                    if len(data) > MAX_TILE_BYTES:
                        self._backoff(None)
                        return None
            result = bytes(data)
            if await self._hass.async_add_executor_job(valid_tile, result):
                return result
        except (ClientError, TimeoutError):
            pass
        self._backoff(None)
        return None

    def _backoff(self, retry_after: str | None) -> None:
        """Pause this provider after failure; source coordinators remain independent."""
        delay = retry_after_seconds(retry_after)
        self._retry_at = max(self._retry_at, time.monotonic() + max(60, delay))
