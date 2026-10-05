"""Source device identity, metadata, and collection availability."""

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import CameraCoordinator, WeatherCoordinator


class WeatherEntity(CoordinatorEntity[WeatherCoordinator]):
    """A source station remains the same device across entry recreation."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: WeatherCoordinator, station_id: str, station_name: str
    ) -> None:
        """Attach to the shared weather coordinator using source identity."""
        super().__init__(coordinator, context=station_id)
        self.station_id = station_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"weather_station:{station_id}")},
            name=station_name,
            manufacturer="Statens vegvesen",
            model="Weather station",
        )

    @property
    def available(self) -> bool:
        """An absent station is unavailable even when the request succeeded."""
        return super().available and self.station_id in self.coordinator.data


class CameraEntity(CoordinatorEntity[CameraCoordinator]):
    """A direction-specific camera's identity and faithful source metadata."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: CameraCoordinator, camera_id: str, camera_name: str
    ) -> None:
        """Attach image and status entities to the same physical device."""
        super().__init__(coordinator, context=camera_id)
        self.camera_id = camera_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"camera:{camera_id}")},
            name=camera_name,
            manufacturer="Statens vegvesen",
            model="Road camera",
        )

    @property
    def available(self) -> bool:
        """Metadata availability is independent of that source's image outcome."""
        return super().available and self.camera_id in self.coordinator.data

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose source publication/update times without inferring capture time."""
        if (snapshot := self.coordinator.data.get(self.camera_id)) is None:
            return {}
        source = snapshot.camera
        return {
            "source_id": source.source_id,
            "latitude": source.latitude,
            "longitude": source.longitude,
            "orientation": source.orientation,
            "road_number": source.road_number,
            "source_availability": source.availability,
            "still_image_service_level": source.service_level,
            "status_still_image_service_level": source.status_service_level,
            "source_publication_time": source.publication_time,
            "source_last_update_time": source.last_update_time,
            "image_error": snapshot.image_error,
        }
