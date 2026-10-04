"""On-demand access to full source forecasts without oversized entity attributes."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import selector

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse

    from .data import VegvesenConfigEntry

SERVICE_FORECASTS = "get_route_forecasts"


def async_setup_route_service(hass: HomeAssistant) -> None:
    """Register once; resolve the current loaded runtime for each action call."""

    async def forecasts(call: ServiceCall) -> ServiceResponse:
        device = dr.async_get(hass).async_get(call.data["device_id"])
        if device is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_route_device"
            )
        entries = [
            entry
            for entry_id in device.config_entries
            if (entry := hass.config_entries.async_get_entry(entry_id)) is not None
            and entry.domain == DOMAIN
        ]
        if not entries or not any(
            domain == DOMAIN and identifier.startswith("route:")
            for domain, identifier in device.identifiers
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_route_device"
            )
        entry = cast("VegvesenConfigEntry", entries[0])
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="route_unavailable"
            )
        coordinator = next(
            (
                r
                for r in entry.runtime_data.routes.values()
                if (DOMAIN, f"route:{r.subentry.data['route_id']}")
                in device.identifiers
            ),
            None,
        )
        if coordinator is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_route_device"
            )
        if not coordinator.last_update_success or coordinator.data is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="route_unavailable"
            )
        snapshot = coordinator.data
        return {
            "route": coordinator.subentry.title,
            "forecast_time": snapshot.forecast_time.isoformat(),
            "segments": [
                {
                    "type": "Feature",
                    "geometry": record.geometry,
                    "properties": record.properties,
                }
                for record in snapshot.segments
            ],
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_FORECASTS,
        forecasts,
        schema=vol.Schema(
            {
                vol.Required("device_id"): selector.DeviceSelector(
                    selector.DeviceSelectorConfig(integration=DOMAIN)
                )
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
