"""Native route settings, candidate selection and an editable overview."""

from __future__ import annotations

import math
from typing import Any
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
from .route_api import RoadRoute, RouteApiClient


class RouteFlow:
    """Share route editing between initial setup and route subentries."""

    _route_data: dict[str, Any]
    _route_choices: list[RoadRoute]
    _route_choice: int = 0

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

    async def async_step_route_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Calculate actual road routes, retaining edits if the service fails."""
        errors = {}
        if user_input is not None:
            changed_stops = any(
                user_input[key] != self._route_data.get(key) for key in ("start", "end")
            )
            if changed_stops:
                self._route_choices = []
            self._route_data.update(user_input)
            valid_points = all(
                all(math.isfinite(point[k]) for k in ("latitude", "longitude"))
                and -90 <= point["latitude"] <= 90  # noqa: PLR2004
                and -180 <= point["longitude"] <= 180  # noqa: PLR2004
                for point in (user_input["start"], user_input["end"])
            )
            if not valid_points or not user_input["name"].strip():
                errors["base"] = "invalid_route"
            else:
                try:
                    if changed_stops or not self._route_choices:
                        # Discard candidates for the old stops, including on failure.
                        self._route_choices = []
                        self._route_choices = await RouteApiClient(
                            async_get_clientsession(self.hass)
                        ).async_routes([user_input["start"], user_input["end"]])
                        self._route_choice = 0
                    if self._route_choices:
                        return await self.async_step_route_overview()
                    errors["base"] = "no_route"
                except VegvesenApiError:
                    errors["base"] = "cannot_connect"
        fields = {
            "name": TextSelector(),
            "start": LocationSelector(),
            "end": LocationSelector(),
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
        schema = vol.Schema(
            {
                (
                    vol.Required(key, default=self._route_data[key])
                    if key in self._route_data
                    else vol.Required(key)
                ): selector
                for key, selector in fields.items()
            }
        )
        return self.async_show_form(
            step_id="route_settings", data_schema=schema, errors=errors
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
                "name": self._route_data["name"],
                "route": route.name,
                "distance": f"{route.length / 1000:.1f}",
                "corridor": f"{self._route_data['corridor_m']:g}",
                "hours": f"{self._route_data['forecast_hours']:g}",
            },
        )

    async def async_step_route_recalculate(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> Any:
        """Explicitly request fresh proposals for the existing endpoints."""
        self._route_choices = []
        return await self.async_step_route_settings(
            {
                key: self._route_data[key]
                for key in ("name", "start", "end", "corridor_m", "forecast_hours")
            }
        )

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
        self._route_data = dict(subentry.data)
        self._route_choices = [
            RoadRoute(
                subentry.data["road_name"],
                subentry.data["length_m"],
                dict(subentry.data["geometry"]),
            )
        ]
        self._route_choice = 0
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
