"""Native image entities for saved routes and their source forecast segments."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.image import ImageEntity
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import ATTRIBUTION, DOMAIN
from .route_coordinator import RouteCoordinator
from .route_map import MapContent
from .route_map_view import MapDocument, async_get_route_maps

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .data import VegvesenConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VegvesenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Attach one image to each existing logical route device and subentry."""
    for subentry_id, coordinator in entry.runtime_data.routes.items():
        async_add_entities(
            [RouteMapImage(hass, coordinator)], config_subentry_id=subentry_id
        )


class RouteMapImage(CoordinatorEntity[RouteCoordinator], ImageEntity):
    """Render cached complete snapshots only when a user requests the image."""

    _attr_has_entity_name = True
    _attr_translation_key = "route_map"
    _attr_content_type = "image/png"
    _attr_attribution = f"{ATTRIBUTION} · © OpenStreetMap contributors"

    def __init__(self, hass: HomeAssistant, coordinator: RouteCoordinator) -> None:
        """Let HA own the image access tokens, entity ID and lifecycle."""
        ImageEntity.__init__(self, hass)
        CoordinatorEntity.__init__(self, coordinator)
        route = coordinator.subentry
        identifier = f"route:{route.data['route_id']}"
        self._attr_unique_id = f"{identifier}:map"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            name=route.title,
            manufacturer="Statens vegvesen",
            model="Route forecast",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._maps = async_get_route_maps(hass)
        self._document: MapDocument | None = None
        self._update_document()

    @callback
    def _update_document(self) -> None:
        if self.coordinator.last_update_success and self.coordinator.data is not None:
            route = self.coordinator.subentry
            self._document = MapDocument(
                MapContent(route.title, route.data["geometry"], self.coordinator.data)
            )
            self._attr_image_last_updated = dt_util.utcnow()
        else:
            self._document = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Invalidate on refresh/failure; image GET never changes its timestamp."""
        self._update_document()
        self.async_write_ha_state()

    async def async_image(self) -> bytes | None:
        """Basemap failures degrade the image without affecting source sensors."""
        document = self._document
        if not self.available or document is None:
            return None
        image = await document.async_image(self._maps)
        return image if self.available and self._document is document else None

    async def async_will_remove_from_hass(self) -> None:
        """Invalidate in-flight renders and remove the coordinator listener."""
        self._document = None
        await super().async_will_remove_from_hass()
