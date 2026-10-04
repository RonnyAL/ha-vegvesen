"""Draft source selections backed by the shared discovery cache."""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .discovery import async_get_discovery

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .api import RoadCamera, WeatherStation

CONF_COUNTY = "county"
CONF_MUNICIPALITY = "municipality"
CONF_SOURCES = "sources"
UNKNOWN = "unknown"


class SourcePicker:
    """Hold an editable draft; persist only source IDs after explicit confirmation."""

    def __init__(self) -> None:
        """Start without automatically choosing a region or source."""
        self.catalogue: dict[str, WeatherStation | RoadCamera] = {}
        self._areas: dict[str, tuple[str, str]] = {}
        self.county: str | None = None
        self.municipality: str | None = None
        self.selected: list[str] = []

    async def async_load(self, hass: HomeAssistant, family: str) -> None:
        """Load one complete catalogue and packaged geography, once per draft."""
        if self.catalogue:
            return
        discovery = async_get_discovery(hass)
        cache = discovery.weather if family == "weather_station" else discovery.cameras
        sources = await cache.async_get()
        locations = await discovery.async_geography()
        for source in sources.values():
            location = locations.get(f"{family}:{source.source_id}")
            if location is not None and (source.latitude, source.longitude) == (
                location.latitude,
                location.longitude,
            ):
                self._areas[source.source_id] = (location.county, location.municipality)
            else:
                self._areas[source.source_id] = (UNKNOWN, UNKNOWN)
        self.catalogue = dict(sources)

    @property
    def counties(self) -> list[str]:
        """Only offer counties containing sources of this family."""
        return sorted({area[0] for area in self._areas.values()}, key=str.casefold)

    @property
    def municipalities(self) -> list[str]:
        """Only offer populated municipalities within the selected county."""
        return sorted(
            {area[1] for area in self._areas.values() if area[0] == self.county},
            key=str.casefold,
        )

    @property
    def sources(self) -> dict[str, WeatherStation | RoadCamera]:
        """Restrict choices and validation to the selected municipality."""
        return {
            source_id: source
            for source_id, source in self.catalogue.items()
            if self._areas[source_id] == (self.county, self.municipality)
        }

    def select_county(self, county: str) -> None:
        """Clear dependent choices only when the county changes."""
        if county != self.county:
            self.county = county
            self.municipality = None
            self.selected = []

    def select_municipality(self, municipality: str) -> None:
        """Clear the source draft when its municipality changes."""
        if municipality != self.municipality:
            self.municipality = municipality
            self.selected = []

    def schema(self, field: str) -> vol.Schema:
        """Use native selectors containing only real regions or source IDs."""
        if field == CONF_SOURCES:
            options = [
                SelectOptionDict(value=source.source_id, label=source.label)
                for source in sorted(
                    self.sources.values(), key=lambda item: item.label.casefold()
                )
            ]
            # Suggested values are editable. A default of the previous selection
            # would restore it when HA omits a cleared optional field.
            marker = vol.Optional(
                field, default=[], description={"suggested_value": self.selected}
            )
        else:
            values = self.counties if field == CONF_COUNTY else self.municipalities
            options = [SelectOptionDict(value=value, label=value) for value in values]
            default = (self.county if field == CONF_COUNTY else self.municipality) or ""
            marker = vol.Required(field, default=default)
        return vol.Schema(
            {
                marker: SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        mode=SelectSelectorMode.DROPDOWN,
                        multiple=field == CONF_SOURCES,
                        custom_value=False,
                        translation_key=field,
                    )
                )
            }
        )
