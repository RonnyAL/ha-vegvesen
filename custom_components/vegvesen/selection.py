"""Native searchable source selection with one final submission."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
    from .discovery import SourceLocation


class SourcePicker:
    """Show only real sources, searchable by county, municipality, name or ID."""

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
        return bool(user_input)

    def schema(self, field: str) -> vol.Schema:
        """Use HA's native autocomplete; the flow validates the chosen source ID."""
        if not self.sources:
            return vol.Schema({})
        family = "weather_station" if field == "station_id" else "camera"
        options = []
        for source in self.sources.values():
            location = self._locations.get(f"{family}:{source.source_id}")
            label = location.label(source) if location else source.label
            options.append(SelectOptionDict(value=source.source_id, label=label))
        return vol.Schema(
            {
                vol.Required(field): SelectSelector(
                    SelectSelectorConfig(
                        options=sorted(
                            options, key=lambda option: option["label"].casefold()
                        ),
                        mode=SelectSelectorMode.DROPDOWN,
                        # The standard HA frontend uses its searchable picker for
                        # custom_value. Unknown input is rejected by our flow.
                        custom_value=True,
                    )
                )
            }
        )
