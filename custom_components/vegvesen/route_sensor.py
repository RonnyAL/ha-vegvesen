"""Small route summaries with explicit source categories and forecast timestamps."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .route_coordinator import RouteCoordinator

if TYPE_CHECKING:
    from datetime import datetime

SOURCE_STATES = {
    "NoNewPrecipitation": "no_new_precipitation",
    "WetRoadSurface": "wet_road_surface",
    "IceOrFrost": "ice_or_frost",
    "SnowCover": "snow_cover",
    "DriftingSnow": "drifting_snow",
    "ErrorOrNoData": "error_or_no_data",
}
CONDITIONS = [*SOURCE_STATES.values(), "mixed", "partial_data"]
SLIP_RISKS = ["low", "medium", "high", "mixed", "partial_data"]
ROUTE_SENSORS = (
    SensorEntityDescription(
        key="road_condition",
        translation_key="route_road_condition",
        device_class=SensorDeviceClass.ENUM,
    ),
    SensorEntityDescription(
        key="slip_risk",
        translation_key="route_slip_risk",
        device_class=SensorDeviceClass.ENUM,
    ),
    SensorEntityDescription(
        key="minimum_road_temperature",
        translation_key="route_minimum_road_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SensorEntityDescription(
        key="maximum_road_temperature",
        translation_key="route_maximum_road_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    SensorEntityDescription(
        key="forecast_time",
        translation_key="route_forecast_time",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(
        key="forecast_segments",
        translation_key="route_forecast_segments",
        native_unit_of_measurement="segments",
    ),
)


class RouteSensor(CoordinatorEntity[RouteCoordinator], SensorEntity):
    """Describe matched forecasts without deriving a route-wide driving-risk score."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self, coordinator: RouteCoordinator, description: SensorEntityDescription
    ) -> None:
        """Own one logical route device, never a physical station or camera."""
        super().__init__(coordinator)
        self.entity_description = description
        route = coordinator.subentry
        identifier = f"route:{route.data['route_id']}"
        self._attr_unique_id = f"{identifier}:{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            name=route.title,
            manufacturer="Statens vegvesen",
            model="Route forecast",
            entry_type=DeviceEntryType.SERVICE,
        )

    def _categories(self) -> Counter[str | None]:
        key = (
            "ROAD_CONDITION"
            if self.entity_description.key == "road_condition"
            else "SLIP_RISK"
        )
        snapshot = self.coordinator.data
        return (
            Counter(record.properties.get(key) for record in snapshot.segments)
            if snapshot
            else Counter()
        )

    @property
    def options(self) -> list[str] | None:
        """Known source codes are translated; new source codes remain usable raw."""
        key = self.entity_description.key
        if key not in {"road_condition", "slip_risk"}:
            return None
        values = CONDITIONS if key == "road_condition" else SLIP_RISKS
        return sorted(
            set(values).union(
                SOURCE_STATES.get(value, value)
                for value in self._categories()
                if value is not None
            )
        )

    @property
    def native_value(self) -> str | int | float | datetime | None:  # noqa: PLR0911
        """Missing coverage is unknown, including zero matching segments."""
        snapshot = self.coordinator.data
        if snapshot is None:
            return None
        key = self.entity_description.key
        if key == "forecast_segments":
            return len(snapshot.segments)
        if not snapshot.segments:
            return None
        if key == "forecast_time":
            return snapshot.forecast_time
        if key in {"road_condition", "slip_risk"}:
            counts = self._categories()
            values = set(counts) - {None, "ErrorOrNoData"}
            if not values:
                return None
            if counts[None] or counts["ErrorOrNoData"]:
                return "partial_data"
            return (
                SOURCE_STATES.get(next(iter(values)), next(iter(values)))
                if len(values) == 1
                else "mixed"
            )
        values = [
            record.properties["ROAD_TEMPERATURE"]
            for record in snapshot.segments
            if record.properties.get("ROAD_TEMPERATURE") is not None
        ]
        if not values:
            return None
        return min(values) if key == "minimum_road_temperature" else max(values)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose counts and target time; retain full segment details only in memory."""
        snapshot = self.coordinator.data
        if snapshot is None:
            return {}
        attributes = {
            "forecast_time": snapshot.forecast_time.isoformat(),
            "matched_segments": len(snapshot.segments),
        }
        if self.entity_description.key in {"road_condition", "slip_risk"}:
            counts = self._categories()
            attributes["source_categories"] = {
                key: count for key, count in counts.items() if key is not None
            }
            attributes["missing_segments"] = counts[None] + counts["ErrorOrNoData"]
        if self.entity_description.key in {
            "minimum_road_temperature",
            "maximum_road_temperature",
        }:
            attributes["missing_segments"] = sum(
                r.properties.get("ROAD_TEMPERATURE") is None for r in snapshot.segments
            )
        return attributes
