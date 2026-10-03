"""Test local module registration, retries and concurrent configuration flows."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, UrlManager

from custom_components.vegvesen.frontend import (
    FRONTEND_URL,
    async_ensure_source_selector,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def test_headless_flow_needs_no_frontend(hass: HomeAssistant) -> None:
    """Source-ID API configuration must work without loading frontend requirements."""
    await async_ensure_source_selector(hass)
    assert "vegvesen_frontend" not in hass.data


async def test_shared_registration(hass: HomeAssistant) -> None:
    """Concurrent flows register one static path and add the page module once."""
    changes = []
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(
        lambda *change: changes.append(change), []
    )
    register = AsyncMock()
    hass.http = SimpleNamespace(async_register_static_paths=register)
    await asyncio.gather(*(async_ensure_source_selector(hass) for _ in range(4)))
    await async_ensure_source_selector(hass)
    register.assert_awaited_once()
    path = register.await_args.args[0][0]
    assert path.url_path == FRONTEND_URL
    assert path.path.endswith("frontend/source-selector.js")
    assert changes == [("added", FRONTEND_URL)]
    assert hass.data[DATA_EXTRA_MODULE_URL].urls == {FRONTEND_URL}


async def test_recreated_frontend_manager(hass: HomeAssistant) -> None:
    """A reset module manager retains the static path and restores its URL."""
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(lambda *_: None, [])
    register = AsyncMock()
    hass.http = SimpleNamespace(async_register_static_paths=register)
    await async_ensure_source_selector(hass)
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(lambda *_: None, [])
    await async_ensure_source_selector(hass)
    register.assert_awaited_once()
    assert hass.data[DATA_EXTRA_MODULE_URL].urls == {FRONTEND_URL}


async def test_failed_registration_can_retry(hass: HomeAssistant) -> None:
    """A failed static-path registration neither loads a broken URL nor blocks retry."""
    hass.data[DATA_EXTRA_MODULE_URL] = UrlManager(lambda *_: None, [])
    register = AsyncMock(side_effect=[OSError("temporary failure"), None])
    hass.http = SimpleNamespace(async_register_static_paths=register)
    with pytest.raises(OSError, match="temporary failure"):
        await async_ensure_source_selector(hass)
    assert not hass.data[DATA_EXTRA_MODULE_URL].urls
    await async_ensure_source_selector(hass)
    assert hass.data[DATA_EXTRA_MODULE_URL].urls == {FRONTEND_URL}
