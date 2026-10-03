"""Entry-scoped runtime resources."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .api import VegvesenApiClient
    from .coordinator import CameraCoordinator, WeatherCoordinator
    from .route_coordinator import RouteCoordinator

type VegvesenConfigEntry = ConfigEntry[VegvesenData]


@dataclass(slots=True)
class VegvesenData:
    """Keep weather and camera resources independently coordinated."""

    client: VegvesenApiClient
    weather: WeatherCoordinator
    cameras: CameraCoordinator
    routes: dict[str, RouteCoordinator] = field(default_factory=dict)
    reload_pending: bool = False
