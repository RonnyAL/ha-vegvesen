"""Native route settings, candidate selection and an editable overview."""

from __future__ import annotations

import math
from copy import deepcopy
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import voluptuous as vol
from homeassistant.config_entries import ConfigSubentryFlow, SubentryFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    LocationSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .api import VegvesenApiError
from .route_api import RoadRoute, RouteApiClient, RoutePointError

if TYPE_CHECKING:
    import asyncio


class RouteFlow:
    """Share route editing between initial setup and route subentries."""

    _route_data: dict[str, Any]
    _route_choices: list[RoadRoute]
    _route_choice: int = 0
    _route_stops: list[dict[str, float]] | None = None
    _calculation_task: asyncio.Task[dict[str, str]] | None = None

    def _initialize_route(self) -> None:
        if not hasattr(self, "_route_data"):
            self._route_data = {
                "route_id": uuid4().hex,
                "corridor_m": 100,
                "forecast_hours": 1,
                # Required location selectors need explicit initial values in HA's
                # native form. Match the map widget's normal home-location seed.
                "start": {
                    "latitude": self.hass.config.latitude,
                    "longitude": self.hass.config.longitude,
                },
                "end": {
                    "latitude": self.hass.config.latitude,
                    "longitude": self.hass.config.longitude,
                },
            }
            self._route_choices = []

    async def async_step_route(self, user_input: dict[str, Any] | None = None) -> Any:
        """Open a new saved route's settings."""
        self._initialize_route()
        return await self.async_step_route_settings(user_input)

    def _endpoint_selector(self) -> SelectSelector:
        """List existing HA zones by friendly name alongside a manual-map option."""
        zones = {
            state.entity_id: state.name for state in self.hass.states.async_all("zone")
        }
        # Keep a removed saved zone visible so it cannot silently turn into a map
        # point or another zone. Calculation reports the missing zone explicitly.
        for endpoint in ("start", "end"):
            source = self._route_data.get(f"{endpoint}_source", "map")
            if source != "map" and source not in zones:
                zones[source] = self._route_data.get(f"{endpoint}_zone_name", source)
        return SelectSelector(
            SelectSelectorConfig(
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="route_endpoint",
                options=[
                    {"value": entity_id, "label": f"{name} ({entity_id})"}
                    for entity_id, name in sorted(
                        zones.items(), key=lambda item: (item[1].casefold(), item[0])
                    )
                ]
                + [{"value": "map", "label": "Choose on map"}],
            )
        )

    async def async_step_route_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Select zones or manual endpoints without rendering unnecessary maps."""
        errors = {}
        if user_input is not None:
            # Empty/omitted means an automatic name; never restore a cleared
            # previous value through the schema's default.
            user_input = {**user_input, "name": user_input.get("name", "").strip()}
            # A number selector's step only controls the widget's increments;
            # it does not enforce whole numbers or reject NaN in the backend.
            hours = user_input["forecast_hours"]
            if not math.isfinite(hours) or not float(hours).is_integer():
                errors["forecast_hours"] = "invalid_forecast_hours"
            if not math.isfinite(user_input["corridor_m"]):
                errors["corridor_m"] = "invalid_corridor"
            self._route_data.update(
                {
                    key: value
                    for key, value in user_input.items()
                    if key not in errors or key == "name"
                }
            )
            if errors:
                return self._route_settings_form(errors)
            if self._manual_endpoints():
                return await self.async_step_route_locations()
            return await self.async_step_route_calculate()
        return self._route_settings_form(errors)

    def _route_settings_form(self, errors: dict[str, str] | None = None) -> Any:
        """Build settings with field errors through HA's public form helper."""
        fields = {
            "name": TextSelector(),
            "start_source": self._endpoint_selector(),
            "end_source": self._endpoint_selector(),
            "corridor_m": NumberSelector(
                NumberSelectorConfig(
                    min=10,
                    max=2000,
                    step=10,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="m",
                )
            ),
            "forecast_hours": NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=24,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="h",
                )
            ),
        }
        defaults = {"start_source": "map", "end_source": "map", **self._route_data}
        schema = vol.Schema(
            {
                (
                    vol.Optional(
                        key,
                        default="",
                        description={"suggested_value": defaults.get(key, "")},
                    )
                    if key == "name"
                    else vol.Required(key, default=defaults[key])
                    if key in defaults
                    else vol.Required(key)
                ): selector
                for key, selector in fields.items()
            }
        )
        return self.async_show_form(
            step_id="route_settings", data_schema=schema, errors=errors
        )

    def _manual_endpoints(self) -> list[str]:
        return [
            key
            for key in ("start", "end")
            if self._route_data.get(f"{key}_source", "map") == "map"
        ]

    async def async_step_route_locations(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Show maps only for endpoints explicitly selected as manual points."""
        if user_input is not None:
            self._route_data.update(user_input)
            return await self.async_step_route_calculate()
        return self._route_locations_form()

    def _route_locations_form(self, errors: dict[str, str] | None = None) -> Any:
        """Render the manual endpoints with their retained draft values."""
        return self.async_show_form(
            step_id="route_locations",
            data_schema=vol.Schema(
                {
                    vol.Required(key, default=self._route_data[key]): LocationSelector()
                    for key in self._manual_endpoints()
                }
            ),
            errors=errors,
        )

    async def async_step_route_calculate(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> Any:
        """Use HA's progress lifecycle for potentially slow routing requests."""
        if self._calculation_task is None:
            self._calculation_task = self.hass.async_create_task(
                self._async_calculate_route()
            )
            if self._calculation_task.done():
                return await self.async_step_route_calculated()
        if not self._calculation_task.done():
            return self.async_show_progress(
                step_id="route_calculate",
                progress_action="calculate_route",
                progress_task=self._calculation_task,
            )
        return self.async_show_progress_done(next_step_id="route_calculated")

    async def async_step_route_calculated(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> Any:
        """Return to an editable form or the proposal overview after calculation."""
        errors = self._calculation_task.result()
        self._calculation_task = None
        if not errors:
            return await self.async_step_route_overview()
        if (
            errors.keys() & {"start_source", "end_source"}
            or not self._manual_endpoints()
        ):
            return self._route_settings_form(errors)
        return self._route_locations_form(errors)

    async def _async_calculate_route(self) -> dict[str, str]:
        """Resolve zones at explicit calculation time and reuse unchanged geometry."""
        for endpoint in ("start", "end"):
            source = self._route_data.get(f"{endpoint}_source", "map")
            if source == "map":
                self._route_data.pop(f"{endpoint}_zone_name", None)
                continue
            zone = self.hass.states.get(source) if source.startswith("zone.") else None
            if zone is None or zone.state in {"unknown", "unavailable"}:
                return {f"{endpoint}_source": "zone_unavailable"}
            point = {k: zone.attributes.get(k) for k in ("latitude", "longitude")}
            if not self._valid_point(point):
                return {f"{endpoint}_source": "zone_unavailable"}
            self._route_data[endpoint] = point
            self._route_data[f"{endpoint}_zone_name"] = zone.name
        stops = [self._route_data[key] for key in ("start", "end")]
        if stops != self._route_stops:
            self._route_choices = []
        if not all(self._valid_point(point) for point in stops):
            return {"base": "invalid_route"}
        try:
            if not self._route_choices:
                self._route_choices = await RouteApiClient(
                    async_get_clientsession(self.hass)
                ).async_routes(stops)
                self._route_choice = 0
                self._route_stops = deepcopy(stops)
        except RoutePointError as err:
            field = err.endpoint
            if self._route_data.get(f"{field}_source", "map") != "map":
                field = f"{field}_source"
            return {field: "off_road_network"}
        except VegvesenApiError:
            return {"base": "cannot_connect"}
        return {} if self._route_choices else {"base": "no_route"}

    @staticmethod
    def _valid_point(point: dict[str, Any]) -> bool:
        """Validate endpoint coordinates without assuming zone attributes exist."""
        return (
            all(
                type(point.get(k)) in (int, float) and math.isfinite(point[k])
                for k in ("latitude", "longitude")
            )
            and -90 <= point["latitude"] <= 90  # noqa: PLR2004
            and -180 <= point["longitude"] <= 180  # noqa: PLR2004
        )

    async def async_step_route_overview(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> Any:
        """Show the selected road proposal and explicit edit/save actions."""
        route = self._route_choices[self._route_choice]
        return self.async_show_menu(
            step_id="route_overview",
            menu_options=[
                "route_settings",
                "route_choice",
                "route_recalculate",
                "route_save",
            ],
            description_placeholders={
                "name": self._route_name(),
                "route": route.name,
                "distance": f"{route.length / 1000:.1f}",
                "corridor": f"{self._route_data['corridor_m']:g}",
                "hours": f"{self._route_data['forecast_hours']:g}",
            },
        )

    def _route_name(self) -> str:
        """Suggest a readable device name; HA generates and owns entity IDs."""
        if name := self._route_data.get("name", "").strip():
            return name
        road_name = self._route_choices[self._route_choice].name
        endpoints = [
            self._route_data.get(f"{endpoint}_zone_name")
            if self._route_data.get(f"{endpoint}_source", "map") != "map"
            else None
            for endpoint in ("start", "end")
        ]
        if all(endpoints):
            return f"{endpoints[0]} → {endpoints[1]}"
        if any(endpoints):
            return " → ".join(name or road_name for name in endpoints)
        return road_name

    async def async_step_route_recalculate(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> Any:
        """Explicitly request fresh proposals for the existing endpoints."""
        self._route_choices = []
        return await self.async_step_route_calculate()

    async def async_step_route_choice(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Choose among the service's road proposals with readable labels."""
        if user_input is not None:
            self._route_choice = int(user_input["route"])
            return await self.async_step_route_overview()
        return self.async_show_form(
            step_id="route_choice",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "route", default=str(self._route_choice)
                    ): SelectSelector(
                        SelectSelectorConfig(
                            mode=SelectSelectorMode.DROPDOWN,
                            options=[
                                {
                                    "value": str(i),
                                    "label": f"{r.name} ({r.length / 1000:.1f} km)",
                                }
                                for i, r in enumerate(self._route_choices)
                            ],
                        )
                    )
                }
            ),
        )

    async def async_step_route_save(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> Any:
        """Persist the road geometry and route settings only after confirmation."""
        route = self._route_choices[self._route_choice]
        self._route_data.update(
            {
                "name": self._route_name(),
                "geometry": route.geometry,
                "road_name": route.name,
                "length_m": route.length,
            }
        )
        return self._save_route()


class RouteSubentryFlow(RouteFlow, ConfigSubentryFlow):
    """A route owns independent settings and retains its identity on reconfigure."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a route without imposing a geographic restriction on the parent."""
        return await self.async_step_route(user_input)

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> SubentryFlowResult:
        """Reopen the saved route without a network call or changing its identity."""
        subentry = self._get_reconfigure_subentry()
        self._route_data = deepcopy(dict(subentry.data))
        self._route_choices = [
            RoadRoute(
                subentry.data["road_name"],
                subentry.data["length_m"],
                dict(subentry.data["geometry"]),
            )
        ]
        self._route_choice = 0
        self._route_stops = deepcopy(
            [self._route_data[key] for key in ("start", "end")]
        )
        return await self.async_step_route_overview()

    def _save_route(self) -> SubentryFlowResult:
        if self.source == "reconfigure":
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                title=self._route_data["name"],
                data=self._route_data,
            )
        return self.async_create_entry(
            title=self._route_data["name"],
            data=self._route_data,
            unique_id=f"route:{self._route_data['route_id']}",
        )
