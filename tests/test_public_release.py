"""Public-facing action failures use HA's native localized exception contract."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.translation import async_get_translations
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vegvesen.const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


@pytest.mark.parametrize("language", ["en", "nb"])
@pytest.mark.parametrize("device_kind", ["missing", "weather_station", "route"])
async def test_localized_action_errors(
    hass: HomeAssistant, language: str, device_kind: str
) -> None:
    """Missing/wrong devices and unloaded routes produce translatable UI errors."""
    assert await async_setup_component(hass, DOMAIN, {})
    device_id = "missing"
    if device_kind != "missing":
        entry = MockConfigEntry(domain=DOMAIN, unique_id="public_service")
        entry.add_to_hass(hass)
        device_id = (
            dr.async_get(hass)
            .async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, f"{device_kind}:example")},
            )
            .id
        )
    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call(
            DOMAIN,
            "get_route_forecasts",
            {"device_id": device_id},
            blocking=True,
            return_response=True,
        )
    key = "route_unavailable" if device_kind == "route" else "invalid_route_device"
    assert error.value.translation_domain == DOMAIN
    assert error.value.translation_key == key
    translations = await async_get_translations(hass, language, "exceptions", {DOMAIN})
    message = translations[f"component.vegvesen.exceptions.{key}.message"]
    assert message.startswith(
        ("Ruteprognosen" if device_kind == "route" else "Velg")
        if language == "nb"
        else ("Route forecasts" if device_kind == "route" else "Select")
    )
