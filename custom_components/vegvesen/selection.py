"""Native county, municipality and source steps backed by cached discovery."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import WeatherStation
from .discovery import async_get_discovery

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .api import RoadCamera

CONF_COUNTY = "county"
CONF_MUNICIPALITY = "municipality"
UNKNOWN = "unknown"
BACK = "back"


def _selector(options: list[SelectOptionDict], translation_key: str) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=options,
            mode=SelectSelectorMode.DROPDOWN,
            custom_value=False,
            translation_key=translation_key,
        )
    )


class SourcePicker:
    """Keep browsing state within one flow; save only the final source ID."""

    def __init__(self) -> None:
        """Start at the county step, with no automatic geographic selection."""
        self._catalogue: dict[str, WeatherStation] | dict[str, RoadCamera] = {}
        self._areas: dict[str, tuple[str, str]] = {}
        self._county: str | None = None
        self._municipality: str | None = None
        self._step = CONF_COUNTY

    @property
    def counties(self) -> list[str]:
        """Only counties containing sources of this family are offered."""
        return sorted({area[0] for area in self._areas.values()}, key=str.casefold)

    @property
    def municipalities(self) -> list[str]:
        """Only municipalities containing sources in this county are offered."""
        return sorted(
            {area[1] for area in self._areas.values() if area[0] == self._county},
            key=str.casefold,
        )

    @property
    def sources(self) -> dict[str, WeatherStation | RoadCamera]:
        """Restrict final validation to the chosen county and municipality."""
        return {
            source_id: source
            for source_id, source in self._catalogue.items()
            if self._areas[source_id] == (self._county, self._municipality)
        }

    @property
    def last_step(self) -> bool:
        """Use HA's Next button for regions and Submit for the source."""
        return self._step == "source"

    def step_id(self, source_step: str) -> str:
        """Use distinct native steps, titles and field labels."""
        if self._step == CONF_COUNTY:
            return f"{source_step}_county"
        if self._step == CONF_MUNICIPALITY:
            return f"{source_step}_municipality"
        return source_step

    async def async_prepare(
        self,
        user_input: dict[str, Any] | None,
        sources: dict[str, WeatherStation] | dict[str, RoadCamera],
        hass: HomeAssistant,
    ) -> bool:
        """Advance native steps using local metadata; no geography HTTP calls."""
        self._catalogue = sources
        locations = await async_get_discovery(hass).async_geography()
        family = (
            "weather_station"
            if isinstance(next(iter(sources.values())), WeatherStation)
            else "camera"
        )
        self._areas = {}
        for source in sources.values():
            location = locations.get(f"{family}:{source.source_id}")
            if location is not None and (
                source.latitude,
                source.longitude,
            ) == (location.latitude, location.longitude):
                self._areas[source.source_id] = (location.county, location.municipality)
            else:
                self._areas[source.source_id] = (UNKNOWN, UNKNOWN)
        if self._county not in self.counties:
            self._county = None
            self._municipality = None
            self._step = CONF_COUNTY
        elif self._municipality not in self.municipalities:
            self._municipality = None
            if self._step == "source":
                self._step = CONF_MUNICIPALITY
        return self._advance(user_input)

    def _advance(self, user_input: dict[str, Any] | None) -> bool:
        """Handle native navigation before considering a source submission."""
        if not user_input:
            return False
        if BACK in user_input.values() and self._step != CONF_COUNTY:
            self._step = CONF_MUNICIPALITY if self._step == "source" else CONF_COUNTY
            return False
        if CONF_COUNTY in user_input:
            county = user_input[CONF_COUNTY]
            if county in self.counties:
                if county != self._county:
                    self._municipality = None
                self._county = county
                self._step = CONF_MUNICIPALITY
            return False
        if CONF_MUNICIPALITY in user_input:
            municipality = user_input[CONF_MUNICIPALITY]
            if municipality in self.municipalities:
                self._municipality = municipality
                self._step = "source"
            return False
        return self.last_step

    def schema(self, field: str) -> vol.Schema:
        """Use built-in dropdowns; no integration-owned frontend is required."""
        if not self._catalogue:
            return vol.Schema({})
        default = ""
        if self._step == CONF_COUNTY:
            key = CONF_COUNTY
            default = self._county or ""
            options = [
                SelectOptionDict(
                    value=value, label="Unknown county" if value == UNKNOWN else value
                )
                for value in self.counties
            ]
        elif self._step == CONF_MUNICIPALITY:
            key = CONF_MUNICIPALITY
            default = self._municipality or ""
            options = [
                SelectOptionDict(value=BACK, label="Change county"),
                *[
                    SelectOptionDict(
                        value=value,
                        label="Unknown municipality" if value == UNKNOWN else value,
                    )
                    for value in self.municipalities
                ],
            ]
        else:
            key = field
            options = [
                SelectOptionDict(value=BACK, label="Change municipality"),
                *[
                    SelectOptionDict(value=source.source_id, label=source.label)
                    for source in sorted(
                        self.sources.values(), key=lambda item: item.label.casefold()
                    )
                ],
            ]
        return vol.Schema({vol.Required(key, default=default): _selector(options, key)})
