"""Manual nationwide weather station and camera selection with HA subentries."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import RoadCamera, VegvesenApiClient, VegvesenApiError, WeatherStation
from .const import (
    CONF_CAMERA_ID,
    CONF_STATION_ID,
    DOMAIN,
    NAME,
    SUBENTRY_CAMERA,
    SUBENTRY_WEATHER_STATION,
)


def _selection_schema(
    stations: dict[str, WeatherStation] | dict[str, RoadCamera], field: str
) -> vol.Schema:
    """Use source names and IDs, without a geographic search restriction."""
    if not stations:
        return vol.Schema({})
    return vol.Schema(
        {
            vol.Required(field): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=station.source_id, label=station.label)
                        for station in sorted(
                            stations.values(),
                            key=lambda station: station.label.casefold(),
                        )
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                    custom_value=False,
                )
            )
        }
    )


class VegvesenConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create one public-service parent and its first selected source."""

    VERSION = 1

    def __init__(self) -> None:
        """Cache discovery only for this flow's lifetime."""
        self._stations: dict[str, WeatherStation] = {}
        self._cameras: dict[str, RoadCamera] = {}

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Choose the first source family without requesting either catalogue."""
        await self.async_set_unique_id("public_service")
        self._abort_if_unique_id_configured()
        return self.async_show_menu(
            step_id="user", menu_options=[SUBENTRY_WEATHER_STATION, SUBENTRY_CAMERA]
        )

    async def async_step_weather_station(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select the first station; credentials and locations are unnecessary."""
        client = VegvesenApiClient(async_get_clientsession(self.hass))
        errors: dict[str, str] = {}
        try:
            if not self._stations:
                self._stations = await client.async_get_weather()
            if user_input and CONF_STATION_ID in user_input:
                station_id = user_input[CONF_STATION_ID]
                selected = await client.async_get_weather({station_id})
                if station_id not in selected:
                    errors["base"] = "station_missing"
                else:
                    self._abort_if_unique_id_configured()
                    station = selected[station_id]
                    return self.async_create_entry(
                        title=NAME,
                        data={},
                        subentries=[
                            {
                                "subentry_type": SUBENTRY_WEATHER_STATION,
                                "unique_id": f"weather_station:{station_id}",
                                "title": station.label,
                                "data": {CONF_STATION_ID: station_id},
                            }
                        ],
                    )
            elif not self._stations:
                errors["base"] = "no_stations"
        except VegvesenApiError:
            errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="weather_station",
            data_schema=_selection_schema(self._stations, CONF_STATION_ID),
            errors=errors,
        )

    async def async_step_camera(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow camera-only setup even when weather discovery is unavailable."""
        client = VegvesenApiClient(async_get_clientsession(self.hass))
        errors: dict[str, str] = {}
        try:
            if not self._cameras:
                self._cameras = await client.async_get_cameras()
            if user_input and CONF_CAMERA_ID in user_input:
                camera_id = user_input[CONF_CAMERA_ID]
                selected = await client.async_get_cameras({camera_id})
                if camera_id not in selected:
                    errors["base"] = "camera_missing"
                else:
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=NAME,
                        data={},
                        subentries=[
                            {
                                "subentry_type": SUBENTRY_CAMERA,
                                "unique_id": f"camera:{camera_id}",
                                "title": selected[camera_id].label,
                                "data": {CONF_CAMERA_ID: camera_id},
                            }
                        ],
                    )
            elif not self._cameras:
                errors["base"] = "no_cameras"
        except VegvesenApiError:
            errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="camera",
            data_schema=_selection_schema(self._cameras, CONF_CAMERA_ID),
            errors=errors,
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls,
        config_entry: ConfigEntry,  # noqa: ARG003
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Allow independent manual station selections under the parent."""
        return {
            SUBENTRY_WEATHER_STATION: WeatherStationSubentryFlow,
            SUBENTRY_CAMERA: CameraSubentryFlow,
        }


class WeatherStationSubentryFlow(ConfigSubentryFlow):
    """Add one source station, rejecting existing selections."""

    def __init__(self) -> None:
        """Cache the catalogue for this flow only."""
        self._stations: dict[str, WeatherStation] = {}

    def _is_configured(self, station_id: str) -> bool:
        """Check source identity, including selections made by other flows."""
        return any(
            subentry.subentry_type == SUBENTRY_WEATHER_STATION
            and subentry.data[CONF_STATION_ID] == station_id
            for subentry in self._get_entry().subentries.values()
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """List stations nationwide and validate the chosen source record."""
        client = VegvesenApiClient(async_get_clientsession(self.hass))
        errors: dict[str, str] = {}
        try:
            if not self._stations:
                self._stations = await client.async_get_weather()
            if user_input and CONF_STATION_ID in user_input:
                station_id = user_input[CONF_STATION_ID]
                if self._is_configured(station_id):
                    return self.async_abort(reason="already_configured")
                selected = await client.async_get_weather({station_id})
                if station_id not in selected:
                    errors["base"] = "station_missing"
                else:
                    # Recheck after I/O, before the manager creates the subentry.
                    if self._is_configured(station_id):
                        return self.async_abort(reason="already_configured")
                    station = selected[station_id]
                    return self.async_create_entry(
                        title=station.label,
                        data={CONF_STATION_ID: station_id},
                        unique_id=f"weather_station:{station_id}",
                    )
            elif not self._stations:
                errors["base"] = "no_stations"
        except VegvesenApiError:
            errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="user",
            data_schema=_selection_schema(self._stations, CONF_STATION_ID),
            errors=errors,
        )


class CameraSubentryFlow(ConfigSubentryFlow):
    """Add a direction-specific camera, rejecting existing source selections."""

    def __init__(self) -> None:
        """Cache discovery only during this flow."""
        self._cameras: dict[str, RoadCamera] = {}

    def _is_configured(self, camera_id: str) -> bool:
        """Check the source ID before and after selection I/O."""
        return any(
            subentry.subentry_type == SUBENTRY_CAMERA
            and subentry.data[CONF_CAMERA_ID] == camera_id
            for subentry in self._get_entry().subentries.values()
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Select a camera nationwide, retaining its source status unchanged."""
        client = VegvesenApiClient(async_get_clientsession(self.hass))
        errors: dict[str, str] = {}
        try:
            if not self._cameras:
                self._cameras = await client.async_get_cameras()
            if user_input and CONF_CAMERA_ID in user_input:
                camera_id = user_input[CONF_CAMERA_ID]
                if self._is_configured(camera_id):
                    return self.async_abort(reason="already_configured")
                selected = await client.async_get_cameras({camera_id})
                if camera_id not in selected:
                    errors["base"] = "camera_missing"
                else:
                    if self._is_configured(camera_id):
                        return self.async_abort(reason="already_configured")
                    return self.async_create_entry(
                        title=selected[camera_id].label,
                        data={CONF_CAMERA_ID: camera_id},
                        unique_id=f"camera:{camera_id}",
                    )
            elif not self._cameras:
                errors["base"] = "no_cameras"
        except VegvesenApiError:
            errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="user",
            data_schema=_selection_schema(self._cameras, CONF_CAMERA_ID),
            errors=errors,
        )
