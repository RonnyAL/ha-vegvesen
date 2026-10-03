"""Three dependent frontend dropdowns with one final source-ID submission."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.helpers.selector import Selector

from .discovery import async_get_discovery
from .frontend import async_ensure_source_selector

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .api import RoadCamera, WeatherStation
    from .discovery import SourceLocation


class SourceSelector(Selector[dict[str, Any]]):
    """Serialize a locally rendered selector while retaining scalar source IDs."""

    selector_type = "vegvesen_source"
    CONFIG_SCHEMA = vol.Schema({vol.Required("options"): [dict]})

    def __call__(self, value: Any) -> str:
        """Leave catalogue membership and duplicate validation to the flow."""
        return vol.Schema(str)(value)


class SourcePicker:
    """Provide real sources and exact-coordinate administrative membership."""

    def __init__(self) -> None:
        """Retain this flow's catalogue and supplemental administrative names."""
        self.sources: dict[str, WeatherStation] | dict[str, RoadCamera] = {}
        self._locations: dict[str, SourceLocation] = {}

    async def async_prepare(
        self,
        user_input: dict[str, Any] | None,
        sources: dict[str, WeatherStation] | dict[str, RoadCamera],
        hass: HomeAssistant,
    ) -> bool:
        """Read shared package metadata without making geography HTTP requests."""
        self.sources = sources
        self._locations = await async_get_discovery(hass).async_geography()
        await async_ensure_source_selector(hass)
        return bool(user_input)

    def schema(self, field: str) -> vol.Schema:
        """Send complete discovery metadata; dropdown changes stay in the browser."""
        if not self.sources:
            return vol.Schema({})
        family = "weather_station" if field == "station_id" else "camera"
        options = []
        for source in self.sources.values():
            location = self._locations.get(f"{family}:{source.source_id}")
            matched = location is not None and (
                source.latitude,
                source.longitude,
            ) == (location.latitude, location.longitude)
            options.append(
                {
                    "value": source.source_id,
                    "label": source.label,
                    "county": location.county if matched else None,
                    "municipality": location.municipality if matched else None,
                }
            )
        return vol.Schema(
            {
                # An explicit blank initial value also avoids HA trying to infer
                # an initial value for an integration-owned selector type.
                vol.Required(field, default=""): SourceSelector(
                    {
                        "options": sorted(
                            options, key=lambda option: option["label"].casefold()
                        )
                    }
                )
            }
        )
