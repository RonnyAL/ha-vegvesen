"""Native selection overviews for weather stations and road cameras."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RoadCamera, VegvesenApiClient, VegvesenApiError, WeatherStation
from .const import (
    CONF_CAMERA_ID,
    CONF_STATION_ID,
    DOMAIN,
    NAME,
    SUBENTRY_CAMERA,
    SUBENTRY_WEATHER_STATION,
)
from .route_flow import RouteFlow, RouteSubentryFlow
from .selection import (
    CONF_COUNTY,
    CONF_MUNICIPALITY,
    CONF_SOURCES,
    UNKNOWN,
    SourcePicker,
)

if TYPE_CHECKING:
    import asyncio


type SelectionResult = ConfigFlowResult | SubentryFlowResult


class SourceFlow:
    """Share the same native overview and editing behavior in all four flows."""

    _family: str
    _picker: SourcePicker
    _discovery_task: asyncio.Task[None] | None = None
    _validation_task: asyncio.Task[dict[str, WeatherStation | RoadCamera]] | None = None

    async def _async_start(self, family: str, retry_step: str) -> SelectionResult:
        self._family = family
        if not hasattr(self, "_picker"):
            self._picker = SourcePicker()
        self._retry_step = retry_step
        return await self.async_step_load_sources()

    async def async_step_load_sources(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> SelectionResult:
        """Let HA display progress and cancel discovery when the flow is closed."""
        if self._discovery_task is None:
            self._discovery_task = self.hass.async_create_task(
                self._picker.async_load(self.hass, self._family)
            )
            # Cached discovery can finish synchronously. Return its real screen,
            # not progress_done as the initial response or a needless spinner.
            if self._discovery_task.done():
                return await self.async_step_sources_loaded()
        if not self._discovery_task.done():
            return self.async_show_progress(
                step_id="load_sources",
                progress_action="load_sources",
                progress_task=self._discovery_task,
            )
        return self.async_show_progress_done(next_step_id="sources_loaded")

    async def async_step_sources_loaded(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> SelectionResult:
        """Show editable discovery errors or the source overview."""
        errors = {}
        try:
            self._discovery_task.result()
            if not self._picker.catalogue:
                errors["base"] = (
                    "no_stations"
                    if self._family == SUBENTRY_WEATHER_STATION
                    else "no_cameras"
                )
        except VegvesenApiError:
            errors["base"] = "cannot_connect"
        finally:
            self._discovery_task = None
        if errors:
            return self.async_show_form(
                step_id=self._retry_step, data_schema=vol.Schema({}), errors=errors
            )
        return self._overview()

    def _overview(self) -> SelectionResult:
        picker = self._picker
        actions = ["county" if picker.county is None else "edit_county"]
        if picker.county is not None:
            actions.append(
                "municipality" if picker.municipality is None else "edit_municipality"
            )
        if picker.municipality is not None:
            actions.append(f"{self._family}_sources")
        if picker.selected:
            actions.append("add")
        return self.async_show_menu(
            step_id=f"{self._family}_overview",
            menu_options=actions,
            description_placeholders={
                "county": picker.county
                if picker.county not in {None, UNKNOWN}
                else "—",
                "municipality": picker.municipality
                if picker.municipality not in {None, UNKNOWN}
                else "—",
                "count": str(len(picker.selected)),
            },
        )

    async def async_step_weather_station_overview(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> SelectionResult:
        """Show the editable weather-station draft."""
        return self._overview()

    async def async_step_camera_overview(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> SelectionResult:
        """Show the editable camera draft."""
        return self._overview()

    async def async_step_county(
        self, user_input: dict[str, Any] | None = None
    ) -> SelectionResult:
        """Edit the county and return to the overview."""
        if user_input is not None:
            self._picker.select_county(user_input[CONF_COUNTY])
            return self._overview()
        return self.async_show_form(
            step_id="county", data_schema=self._picker.schema(CONF_COUNTY)
        )

    async def async_step_edit_county(
        self, user_input: dict[str, Any] | None = None
    ) -> SelectionResult:
        """Expose an explicit edit action after the first county choice."""
        return await self.async_step_county(user_input)

    async def async_step_municipality(
        self, user_input: dict[str, Any] | None = None
    ) -> SelectionResult:
        """Edit the municipality and return to the overview."""
        if user_input is not None:
            self._picker.select_municipality(user_input[CONF_MUNICIPALITY])
            return self._overview()
        return self.async_show_form(
            step_id="municipality", data_schema=self._picker.schema(CONF_MUNICIPALITY)
        )

    async def async_step_edit_municipality(
        self, user_input: dict[str, Any] | None = None
    ) -> SelectionResult:
        """Expose an explicit edit action after the first municipality choice."""
        return await self.async_step_municipality(user_input)

    def _sources_form(self, error: str | None = None) -> SelectionResult:
        return self.async_show_form(
            step_id=f"{self._family}_sources",
            data_schema=self._picker.schema(CONF_SOURCES),
            errors={"base": error} if error else {},
        )

    async def _async_sources(
        self, user_input: dict[str, Any] | None
    ) -> SelectionResult:
        if user_input is not None:
            # Preserve order, while ensuring a repeated ID creates only one source.
            selected = list(dict.fromkeys(user_input[CONF_SOURCES]))
            if any(source_id not in self._picker.sources for source_id in selected):
                return self._sources_form("invalid_source")
            self._picker.selected = selected
            return self._overview()
        return self._sources_form()

    async def async_step_weather_station_sources(
        self, user_input: dict[str, Any] | None = None
    ) -> SelectionResult:
        """Edit the weather-station draft."""
        return await self._async_sources(user_input)

    async def async_step_camera_sources(
        self, user_input: dict[str, Any] | None = None
    ) -> SelectionResult:
        """Edit the camera draft."""
        return await self._async_sources(user_input)

    def _has_duplicates(self) -> bool:
        return False

    async def async_step_add(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> SelectionResult:
        """Validate every selected record before saving any source."""
        ids = set(self._picker.selected)
        if not ids or not ids.issubset(self._picker.sources):
            return self._sources_form("invalid_source")
        if self._has_duplicates():
            return self._sources_form("already_configured")
        return await self.async_step_validate_sources()

    async def async_step_validate_sources(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> SelectionResult:
        """Validate in a cancellable task; do not save from the background task."""
        if self._validation_task is None:
            client = VegvesenApiClient(async_get_clientsession(self.hass))
            ids = set(self._picker.selected)
            self._validation_task = self.hass.async_create_task(
                client.async_get_weather(ids)
                if self._family == SUBENTRY_WEATHER_STATION
                else client.async_get_cameras(ids)
            )
            if self._validation_task.done():
                return await self.async_step_sources_validated()
        if not self._validation_task.done():
            return self.async_show_progress(
                step_id="validate_sources",
                progress_action="validate_sources",
                progress_task=self._validation_task,
            )
        return self.async_show_progress_done(next_step_id="sources_validated")

    async def async_step_sources_validated(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> SelectionResult:
        """Recheck duplicates and commit only while HA is advancing a live flow."""
        try:
            selected = self._validation_task.result()
        except VegvesenApiError:
            return self._sources_form("cannot_connect")
        finally:
            self._validation_task = None
        if not set(self._picker.selected).issubset(selected):
            return self._sources_form(
                "station_missing"
                if self._family == SUBENTRY_WEATHER_STATION
                else "camera_missing"
            )
        # Concurrent flows may finish during network I/O. No await occurs between
        # this final check and saving the full batch through HA's subentry APIs.
        if self._has_duplicates():
            return self._sources_form("already_configured")
        return self._save_selection(
            [selected[source_id] for source_id in self._picker.selected]
        )


class VegvesenConfigFlow(RouteFlow, SourceFlow, ConfigFlow, domain=DOMAIN):
    """Create a single parent with one subentry per selected physical source."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Choose a family without requesting either catalogue."""
        await self.async_set_unique_id("public_service")
        self._abort_if_unique_id_configured()
        return self.async_show_menu(
            step_id="user",
            menu_options=[SUBENTRY_WEATHER_STATION, SUBENTRY_CAMERA, "route"],
        )

    async def async_step_weather_station(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> SelectionResult:
        """Start a weather selection or retry failed discovery."""
        return await self._async_start(SUBENTRY_WEATHER_STATION, "weather_station")

    async def async_step_camera(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> SelectionResult:
        """Start camera selection independently of weather discovery."""
        return await self._async_start(SUBENTRY_CAMERA, "camera")

    def _save_selection(
        self, selected: list[WeatherStation | RoadCamera]
    ) -> ConfigFlowResult:
        self._abort_if_unique_id_configured()
        field = (
            CONF_STATION_ID
            if self._family == SUBENTRY_WEATHER_STATION
            else CONF_CAMERA_ID
        )
        return self.async_create_entry(
            title=NAME,
            data={},
            subentries=[
                {
                    "subentry_type": self._family,
                    "unique_id": f"{self._family}:{source.source_id}",
                    "title": source.label,
                    "data": {field: source.source_id},
                }
                for source in selected
            ],
        )

    def _save_route(self) -> ConfigFlowResult:
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=NAME,
            data={},
            subentries=[
                {
                    "subentry_type": "route",
                    "title": self._route_data["name"],
                    "unique_id": f"route:{self._route_data['route_id']}",
                    "data": self._route_data,
                }
            ],
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls,
        config_entry: ConfigEntry,  # noqa: ARG003
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Add further independent source selections under this parent."""
        return {
            SUBENTRY_WEATHER_STATION: WeatherStationSubentryFlow,
            SUBENTRY_CAMERA: CameraSubentryFlow,
            "route": RouteSubentryFlow,
        }


class SourceSubentryFlow(SourceFlow, ConfigSubentryFlow):
    """Validate a whole batch before adding its individual source subentries."""

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> SelectionResult:
        """Open the selection overview or retry discovery."""
        return await self._async_start(self._family, "user")

    def _has_duplicates(self) -> bool:
        field = (
            CONF_STATION_ID
            if self._family == SUBENTRY_WEATHER_STATION
            else CONF_CAMERA_ID
        )
        configured = {
            subentry.data[field]
            for subentry in self._get_entry().subentries.values()
            if subentry.subentry_type == self._family
        }
        return bool(configured.intersection(self._picker.selected))

    def _save_selection(
        self, selected: list[WeatherStation | RoadCamera]
    ) -> SubentryFlowResult:
        entry = self._get_entry()
        field = (
            CONF_STATION_ID
            if self._family == SUBENTRY_WEATHER_STATION
            else CONF_CAMERA_ID
        )
        # HA's subentry flow result creates one subentry. Add the rest using its
        # public API, synchronously, after validating the entire selection.
        for source in selected[1:]:
            self.hass.config_entries.async_add_subentry(
                entry,
                ConfigSubentry(
                    subentry_type=self._family,
                    unique_id=f"{self._family}:{source.source_id}",
                    title=source.label,
                    data={field: source.source_id},
                ),
            )
        source = selected[0]
        return self.async_create_entry(
            title=source.label,
            data={field: source.source_id},
            unique_id=f"{self._family}:{source.source_id}",
        )


class WeatherStationSubentryFlow(SourceSubentryFlow):
    """Add weather stations with stable source identities."""

    _family = SUBENTRY_WEATHER_STATION


class CameraSubentryFlow(SourceSubentryFlow):
    """Add road cameras with stable direction-specific source identities."""

    _family = SUBENTRY_CAMERA
