"""Load only this integration's source selector, without changing HA widgets."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

FRONTEND_VERSION = "0.4.0"
FRONTEND_URL = f"/vegvesen/frontend/{FRONTEND_VERSION}/source-selector.js"
_DATA_KEY = "vegvesen_frontend"


class FrontendRegistration:
    """One registration per HA instance; no tasks or timers to unload."""

    def __init__(self) -> None:
        """Coalesce flows and remember successful static-path registration."""
        self.lock = asyncio.Lock()
        self.static_registered = False


async def async_ensure_source_selector(hass: HomeAssistant) -> None:
    """Register a local versioned module for subsequent frontend page loads."""
    # A headless API client can configure by source ID without a frontend.
    if frontend.DATA_EXTRA_MODULE_URL not in hass.data:
        return
    registration = hass.data.setdefault(_DATA_KEY, FrontendRegistration())
    async with registration.lock:
        if not registration.static_registered:
            await hass.http.async_register_static_paths(
                [
                    StaticPathConfig(
                        FRONTEND_URL,
                        str(
                            Path(__file__).with_name("frontend") / "source-selector.js"
                        ),
                        cache_headers=True,
                    )
                ]
            )
            registration.static_registered = True
        if FRONTEND_URL not in hass.data[frontend.DATA_EXTRA_MODULE_URL].urls:
            frontend.add_extra_js_url(hass, FRONTEND_URL)
