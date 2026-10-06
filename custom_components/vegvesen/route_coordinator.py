"""Forecast refreshes isolated per saved route, independent of measured weather."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import TYPE_CHECKING

from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import VegvesenApiError, VegvesenRateLimitError
from .const import LOGGER
from .route_geometry import RouteCorridor, make_corridor

FORECAST_CACHE_TTL = 5 * 60
FORECAST_CACHE_SIZE = 4
FORECAST_QUERY_TIMEOUT = 40

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
    retrieved_at: datetime | None = field(default=None, compare=False)


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
        self._entry = entry
        self._forecast_cache: OrderedDict[datetime, tuple[float, RouteSnapshot]] = (
            OrderedDict()
        )
        self._forecast_tasks: dict[datetime, asyncio.Task[RouteSnapshot]] = {}
        self._forecast_lock = asyncio.Lock()
        self.forecasts_closed = False
        entry.async_on_unload(self._close_forecasts)

    @callback
    def _close_forecasts(self) -> None:
        """Clear this geometry's cache; HA also owns/cancels the background tasks."""
        self.forecasts_closed = True
        self._forecast_cache.clear()
        for task in self._forecast_tasks.values():
            task.cancel()

    async def async_forecast(
        self, target: datetime, *, refresh: bool = False
    ) -> RouteSnapshot:
        """
        Share complete snapshots and in-flight results across actions and polling.

        Explicit queries never publish entity state or change the saved offset.
        Polling/manual entity refresh bypasses the cache, retaining its schedule.
        """
        if self.forecasts_closed:
            raise VegvesenApiError("Route has unloaded")
        if (task := self._forecast_tasks.get(target)) is not None and not task.done():
            return await asyncio.shield(task)
        self._forecast_tasks.pop(target, None)
        cached = self._forecast_cache.get(target)
        if not refresh and cached and monotonic() < cached[0]:
            self._forecast_cache.move_to_end(target)
            return cached[1]
        # A failed refresh must not leave an older snapshot available as fresh.
        self._forecast_cache.pop(target, None)
        task = self._entry.async_create_background_task(
            self.hass,
            self._fetch_forecast(target),
            "Vegvesen forecast hour",
            eager_start=True,
        )
        self._forecast_tasks[target] = task

        @callback
        def finished(done: asyncio.Task[RouteSnapshot]) -> None:
            if self._forecast_tasks.get(target) is done:
                self._forecast_tasks.pop(target, None)
            # A caller may have cancelled while others (or the cache) still need
            # the request. Retrieve exceptions even when no callers remain.
            if not done.cancelled():
                done.exception()

        task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def _fetch_forecast(self, target: datetime) -> RouteSnapshot:
        """Bound queueing and transport, and cache only a fully matched response."""
        try:
            async with asyncio.timeout(FORECAST_QUERY_TIMEOUT), self._forecast_lock:
                if self.corridor is None:
                    await self._async_setup()
                records = await self.client.async_forecasts(self.corridor.bbox, target)
                segments = await self.hass.async_add_executor_job(
                    select_segments, self.corridor, records
                )
                snapshot = RouteSnapshot(target, segments, datetime.now(UTC))
                self._forecast_cache[target] = (
                    monotonic() + FORECAST_CACHE_TTL,
                    snapshot,
                )
                self._forecast_cache.move_to_end(target)
                while len(self._forecast_cache) > FORECAST_CACHE_SIZE:
                    self._forecast_cache.popitem(last=False)
                return snapshot
        except TimeoutError as err:
            raise VegvesenApiError("Forecast request timed out") from err

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
            return await self.async_forecast(target, refresh=True)
        except VegvesenRateLimitError as err:
            raise UpdateFailed(str(err), retry_after=err.retry_after) from err
        except VegvesenApiError as err:
            raise UpdateFailed(str(err)) from err
