"""Entry-scoped runtime resources."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .api import VegvesenApiClient
    from .coordinator import CameraCoordinator, WeatherCoordinator
    from .route_coordinator import RouteCoordinator
    from .route_sources import CameraFrames, SourceCoordinator

type VegvesenConfigEntry = ConfigEntry[VegvesenData]


@dataclass(slots=True)
class VegvesenData:
    """Keep weather and camera resources independently coordinated."""

    client: VegvesenApiClient
    weather: WeatherCoordinator
    cameras: CameraCoordinator
    routes: dict[str, RouteCoordinator] = field(default_factory=dict)
    sources: dict[str, SourceCoordinator] = field(default_factory=dict)
    camera_frames: CameraFrames | None = None
    reload_pending: bool = False
