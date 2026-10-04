"""Forecast refreshes isolated per saved route, independent of measured weather."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import VegvesenApiError, VegvesenRateLimitError
from .const import LOGGER
from .route_geometry import RouteCorridor, make_corridor

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigSubentry
    from homeassistant.core import HomeAssistant

    from .data import VegvesenConfigEntry
    from .route_api import RoadForecast, RouteApiClient


@dataclass(frozen=True, slots=True)
class RouteSnapshot:
    """A complete response for one explicit forecast time and saved corridor."""

    forecast_time: datetime
    segments: tuple[RoadForecast, ...]


def select_segments(
    corridor: RouteCorridor, records: dict[str, RoadForecast]
) -> tuple[RoadForecast, ...]:
    """Apply the actual corridor after complete pagination, in an executor."""
    return tuple(
        record for record in records.values() if corridor.intersects(record.geometry)
    )


class RouteCoordinator(DataUpdateCoordinator[RouteSnapshot | None]):
    """Poll source forecasts without silently recalculating the saved road route."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: VegvesenConfigEntry,
        subentry: ConfigSubentry,
        client: RouteApiClient,
    ) -> None:
        """Create a coordinator using only this route's settings."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"Statens vegvesen route {subentry.subentry_id}",
            update_interval=timedelta(minutes=30),
            always_update=False,
        )
        self.subentry = subentry
        self.client = client
        self.corridor: RouteCorridor | None = None
        self.data = None

    def _forecast_target(self, now: datetime) -> datetime:
        """Select the configured offset from the current UTC hour."""
        return now.replace(minute=0, second=0, microsecond=0) + timedelta(
            hours=self.subentry.data["forecast_hours"]
        )

    @callback
    def _schedule_refresh(self) -> None:
        """Align HA's single polling timer while retaining its retry/lifecycle rules."""
        now = datetime.now(UTC)
        boundary = now.replace(
            minute=(now.minute // 30) * 30, second=0, microsecond=0
        ) + timedelta(minutes=30)
        # A slow request can finish in a different hour than it started in.
        if (
            self.last_update_success
            and self.data is not None
            and self.data.forecast_time != self._forecast_target(now)
        ):
            boundary = now
        # HA rounds its monotonic timer; avoid requesting the previous hour just
        # before the boundary. A server Retry-After still takes precedence.
        self.update_interval = boundary - now + timedelta(seconds=1)
        super()._schedule_refresh()

    async def _async_setup(self) -> None:
        """Construct the route's metric corridor without blocking HA."""
        self.corridor = await self.hass.async_add_executor_job(
            make_corridor,
            self.subentry.data["geometry"],
            self.subentry.data["corridor_m"],
        )

    async def _async_update_data(self) -> RouteSnapshot:
        """Publish nothing until fetching and geographic matching both succeed."""
        target = self._forecast_target(datetime.now(UTC))
        try:
            if self.corridor is None:
                await self._async_setup()
            records = await self.client.async_forecasts(self.corridor.bbox, target)
            segments = await self.hass.async_add_executor_job(
                select_segments, self.corridor, records
            )
        except VegvesenRateLimitError as err:
            raise UpdateFailed(str(err), retry_after=err.retry_after) from err
        except VegvesenApiError as err:
            raise UpdateFailed(str(err)) from err
        return RouteSnapshot(target, segments)
