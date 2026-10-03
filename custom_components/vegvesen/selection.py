"""A flow-local fylke/kommune picker shared by manual source selections."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .geography import GeographyClient

if TYPE_CHECKING:
    import aiohttp

    from .api import RoadCamera, WeatherStation
    from .geography import County

CONF_COUNTY = "county"
CONF_MUNICIPALITY = "municipality"
ALL = "all"


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
    """Browse independently for each new subentry; save only the source ID."""

    def __init__(self) -> None:
        """Keep all administrative state and caches within this flow."""
        self._client: GeographyClient | None = None
        self._counties: dict[str, County] = {}
        self._county: str | None = None
        self._municipality: str | None = None
        self.sources: dict[str, WeatherStation] | dict[str, RoadCamera] | None = None

    async def async_prepare(
        self,
        user_input: dict[str, Any] | None,
        sources: dict[str, WeatherStation] | dict[str, RoadCamera],
        session: aiohttp.ClientSession,
    ) -> bool:
        """Advance browsing; return true only when a source can be submitted."""
        if self._client is None:
            self._client = GeographyClient(session)
        requested_county = (user_input or {}).get(CONF_COUNTY, self._county)
        # All Norway remains usable even if Kartverket is unavailable.
        if requested_county != ALL and not self._counties:
            self._counties = await self._client.async_get_counties()
        if user_input is None:
            return False
        if requested_county != self._county:
            self._county = requested_county
            self._municipality = None
            self.sources = sources if self._county == ALL else None
            return False
        if self._county == ALL:
            self.sources = sources
            return True
        if self._county is None:
            return False
        municipality = user_input.get(CONF_MUNICIPALITY)
        if municipality is not None and (
            municipality != self._municipality or self.sources is None
        ):
            self._municipality = municipality
            self.sources = None
            self.sources = await self._client.async_filter(
                sources,
                self._counties[self._county],
                None if municipality == ALL else municipality,
            )
            return False
        return municipality is not None

    def schema(self, field: str) -> vol.Schema:
        """Retain region controls so users can change a filter without restarting."""
        fields: dict[Any, Any] = {
            vol.Required(CONF_COUNTY, default=self._county or ALL): _selector(
                [SelectOptionDict(value=ALL, label="All Norway")]
                + [
                    SelectOptionDict(value=county.number, label=county.name)
                    for county in sorted(
                        self._counties.values(),
                        key=lambda county: county.name.casefold(),
                    )
                ],
                "county",
            )
        }
        if self._county not in (None, ALL):
            fields[
                vol.Required(CONF_MUNICIPALITY, default=self._municipality or ALL)
            ] = _selector(
                [SelectOptionDict(value=ALL, label="All municipalities")]
                + [
                    SelectOptionDict(value=item.number, label=item.name)
                    for item in sorted(
                        self._counties[self._county].municipalities.values(),
                        key=lambda item: item.name.casefold(),
                    )
                ],
                "municipality",
            )
        if self.sources:
            fields[vol.Optional(field)] = _selector(
                [
                    SelectOptionDict(value=source.source_id, label=source.label)
                    for source in sorted(
                        self.sources.values(),
                        key=lambda source: source.label.casefold(),
                    )
                ],
                "source",
            )
        return vol.Schema(fields)
