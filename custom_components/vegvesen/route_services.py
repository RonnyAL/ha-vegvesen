"""On-demand route forecast hours and summaries for native HA automations."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import TYPE_CHECKING, cast

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from .api import VegvesenApiError, VegvesenRateLimitError
from .const import DOMAIN
from .route_summary import forecast_summary

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse

    from .data import VegvesenConfigEntry
    from .route_coordinator import RouteCoordinator

SERVICE_FORECASTS = "get_route_forecasts"
MAX_FORECAST_HOURS = 24  # Integration limit, not an upstream horizon guarantee.


@callback
def _route(
    hass: HomeAssistant, device_id: str
) -> tuple[VegvesenConfigEntry, RouteCoordinator]:
    """Resolve the current runtime from stable device identity on every call."""
    registry = dr.async_get(hass)
    device = registry.async_get(device_id)
    if device is not None:
        for candidate in hass.config_entries.async_entries(DOMAIN):
            if device not in dr.async_entries_for_config_entry(
                registry, candidate.entry_id
            ):
                continue
            if not any(
                domain == DOMAIN and identifier.startswith("route:")
                for domain, identifier in device.identifiers
            ):
                continue
            entry = cast("VegvesenConfigEntry", candidate)
            if entry.state is not ConfigEntryState.LOADED or device.disabled:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="route_unavailable"
                )
            for coordinator in entry.runtime_data.routes.values():
                subentry = coordinator.subentry
                if (
                    DOMAIN,
                    f"route:{subentry.data['route_id']}",
                ) in device.identifiers and entry.subentries.get(
                    subentry.subentry_id
                ) is subentry:
                    return entry, coordinator
    raise ServiceValidationError(
        translation_domain=DOMAIN, translation_key="invalid_route_device"
    )


def forecast_hour(value: object) -> tuple[datetime, datetime]:
    """Use HA's local-time convention, then select the containing UTC hour."""
    requested = dt_util.as_utc(cv.datetime(value))
    target = requested.replace(minute=0, second=0, microsecond=0)
    current = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    if not current <= target <= current + timedelta(hours=MAX_FORECAST_HOURS):
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="forecast_time_out_of_range"
        )
    return requested, target


def async_setup_route_service(hass: HomeAssistant) -> None:
    """Register once; action requests do not mutate route configuration or state."""

    async def forecasts(call: ServiceCall) -> ServiceResponse:
        entry, coordinator = _route(hass, call.data["device_id"])
        requested = None
        if "forecast_time" in call.data:
            requested, target = forecast_hour(call.data["forecast_time"])
            try:
                snapshot = await coordinator.async_forecast(target)
            except asyncio.CancelledError:
                if not coordinator.forecasts_closed:
                    raise
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="route_unavailable"
                ) from None
            except VegvesenRateLimitError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="forecast_rate_limited",
                    translation_placeholders={"seconds": str(ceil(err.retry_after))},
                ) from err
            except VegvesenApiError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="forecast_request_failed"
                ) from err
            # Recheck identity after I/O, including reload, removal or reconfiguration.
            current_entry, current = _route(hass, call.data["device_id"])
            if current_entry is not entry or current is not coordinator:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="route_unavailable"
                )
        else:
            # Keep the original no-I/O contract, including failure behavior.
            if not coordinator.last_update_success or coordinator.data is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="route_unavailable"
                )
            snapshot = coordinator.data
        response = {
            "route": coordinator.subentry.title,
            "forecast_time": snapshot.forecast_time.isoformat(),
            "requested_time": requested.isoformat() if requested else None,
            "retrieved_at": snapshot.retrieved_at.isoformat()
            if snapshot.retrieved_at
            else None,
            "summary": forecast_summary(snapshot),
        }
        if call.data.get("include_segments", True):
            response["segments"] = [
                {
                    "type": "Feature",
                    "geometry": record.geometry,
                    "properties": record.properties,
                }
                for record in snapshot.segments
            ]
        return response

    hass.services.async_register(
        DOMAIN,
        SERVICE_FORECASTS,
        forecasts,
        schema=vol.Schema(
            {
                vol.Required("device_id"): selector.DeviceSelector(
                    selector.DeviceSelectorConfig(integration=DOMAIN)
                ),
                vol.Optional("forecast_time"): selector.DateTimeSelector(),
                vol.Optional(
                    "include_segments", default=True
                ): selector.BooleanSelector(),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
