"""Weather observations and raw source camera availability."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature

from .const import (
    CONF_CAMERA_ID,
    CONF_STATION_ID,
    SUBENTRY_CAMERA,
    SUBENTRY_WEATHER_STATION,
)
from .entity import CameraEntity, WeatherEntity

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import CameraCoordinator, WeatherCoordinator
    from .data import VegvesenConfigEntry

SENSORS = (
    SensorEntityDescription(
        key="air_temperature",
        translation_key="air_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="measurement_time",
        translation_key="measurement_time",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
)
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: VegvesenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Register weather observations and source camera status under their subentries."""
    coordinator = entry.runtime_data.weather
    for subentry in entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_CAMERA:
            camera_id = subentry.data[CONF_CAMERA_ID]
            snapshot = entry.runtime_data.cameras.data.get(camera_id)
            async_add_entities(
                [
                    CameraStatusSensor(
                        entry.runtime_data.cameras,
                        camera_id,
                        snapshot.camera.label if snapshot else subentry.title,
                    )
                ],
                config_subentry_id=subentry.subentry_id,
            )
            continue
        if subentry.subentry_type != SUBENTRY_WEATHER_STATION:
            continue
        station_id = subentry.data[CONF_STATION_ID]
        station = coordinator.data.get(station_id)
        async_add_entities(
            [
                WeatherSensor(
                    coordinator,
                    station_id,
                    station.name if station else subentry.title,
                    description,
                )
                for description in SENSORS
            ],
            config_subentry_id=subentry.subentry_id,
        )


class WeatherSensor(WeatherEntity, SensorEntity):
    """Return native source values, including null and unusual numbers."""

    def __init__(
        self,
        coordinator: WeatherCoordinator,
        station_id: str,
        station_name: str,
        description: SensorEntityDescription,
    ) -> None:
        """Include the measurement key in stable entity identity."""
        super().__init__(coordinator, station_id, station_name)
        self.entity_description = description
        self._attr_unique_id = f"weather_station:{station_id}:{description.key}"

    @property
    def native_value(self) -> int | float | datetime | None:
        """A missing measurement is unknown; old failed data is unavailable."""
        if (station := self.coordinator.data.get(self.station_id)) is None:
            return None
        return getattr(station, self.entity_description.key)


class CameraStatusSensor(CameraEntity, SensorEntity):
    """Expose the raw source status even when its JPEG is unavailable."""

    _attr_translation_key = "source_availability"

    def __init__(
        self, coordinator: CameraCoordinator, camera_id: str, camera_name: str
    ) -> None:
        """Use a stable measurement identity on the physical camera's device."""
        super().__init__(coordinator, camera_id, camera_name)
        self._attr_unique_id = f"camera:{camera_id}:availability"

    @property
    def native_value(self) -> str | None:
        """Null source status is unknown; collection failure is unavailable."""
        if (snapshot := self.coordinator.data.get(self.camera_id)) is None:
            return None
        return snapshot.camera.availability
