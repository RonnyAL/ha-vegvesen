"""Entry-scoped runtime resources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .api import VegvesenApiClient
    from .coordinator import CameraCoordinator, WeatherCoordinator

type VegvesenConfigEntry = ConfigEntry[VegvesenData]


@dataclass(slots=True)
class VegvesenData:
    """Keep weather and camera resources independently coordinated."""

    client: VegvesenApiClient
    weather: WeatherCoordinator
    cameras: CameraCoordinator
    reload_pending: bool = False
