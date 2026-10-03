"""On-demand access to full source forecasts without oversized entity attributes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import selector

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse

    from .data import VegvesenConfigEntry

SERVICE_FORECASTS = "get_route_forecasts"


def async_setup_route_service(hass: HomeAssistant, entry: VegvesenConfigEntry) -> None:
    """Register a response-only action and remove it when this parent unloads."""

    async def forecasts(call: ServiceCall) -> ServiceResponse:
        device = dr.async_get(hass).async_get(call.data["device_id"])
        if device is None or entry.entry_id not in device.config_entries:
            raise ServiceValidationError("Select a Statens vegvesen route device")
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
            raise ServiceValidationError("Select a route forecast device")
        if not coordinator.last_update_success or coordinator.data is None:
            raise ServiceValidationError("Route forecasts are unavailable")
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
    entry.async_on_unload(lambda: hass.services.async_remove(DOMAIN, SERVICE_FORECASTS))
