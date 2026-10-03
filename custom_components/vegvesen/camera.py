"""Source-provided road camera stills served from the coordinator cache."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.camera import Camera

from .const import CONF_CAMERA_ID, SUBENTRY_CAMERA
from .entity import CameraEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import CameraCoordinator
    from .data import VegvesenConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: VegvesenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Register one still camera per source subentry."""
    coordinator = entry.runtime_data.cameras
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_CAMERA:
            continue
        camera_id = subentry.data[CONF_CAMERA_ID]
        snapshot = coordinator.data.get(camera_id)
        name = snapshot.camera.label if snapshot else subentry.title
        async_add_entities(
            [VegvesenCamera(coordinator, camera_id, name)],
            config_subentry_id=subentry.subentry_id,
        )


class VegvesenCamera(CameraEntity, Camera):
    """A physical direction-specific source camera, without inferred capture time."""

    _attr_name = None

    def __init__(
        self, coordinator: CameraCoordinator, camera_id: str, camera_name: str
    ) -> None:
        """Initialize HA camera tokens and stable source identity."""
        Camera.__init__(self)
        CameraEntity.__init__(self, coordinator, camera_id, camera_name)
        self._attr_unique_id = f"camera:{camera_id}"

    @property
    def available(self) -> bool:
        """Only a successful current collection and image can be displayed."""
        snapshot = self.coordinator.data.get(self.camera_id)
        return super().available and snapshot is not None and snapshot.image is not None

    async def async_camera_image(
        self,
        width: int | None = None,  # noqa: ARG002
        height: int | None = None,  # noqa: ARG002
    ) -> bytes | None:
        """Serve the cached source JPEG; HA handles display scaling."""
        if not self.available:
            return None
        return self.coordinator.data[self.camera_id].image
