"""Exercise real HA coordinator timers with mocked public forecast responses."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from aioresponses import CallbackResult
from homeassistant.const import STATE_UNAVAILABLE
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.vegvesen.const import DOMAIN
from custom_components.vegvesen.route_geometry import make_corridor

from .helpers import page
from .test_routes import forecast_url, source_entity

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aioresponses import aioresponses
    from freezegun.api import FrozenDateTimeFactory
    from homeassistant.core import HomeAssistant

    from custom_components.vegvesen.route_coordinator import RouteCoordinator

    Clock = tuple[datetime, Callable[..., None], Callable[[datetime], Awaitable[None]]]


@pytest.fixture
def forecast_clock(
    hass: HomeAssistant,
    mock_http: aioresponses,
    route_data: dict[str, Any],
    forecasts: list[dict[str, Any]],
    freezer: FrozenDateTimeFactory,
) -> Clock:
    """Register complete snapshots for explicit hours and advance HA's timers."""
    target = datetime(2026, 10, 4, 15, tzinfo=UTC)
    freezer.move_to(target - timedelta(minutes=25))
    bbox = make_corridor(route_data["geometry"], 100).bbox

    def respond(hour: datetime, **kwargs: Any) -> None:
        records = deepcopy(forecasts)
        for record in records:
            record["properties"]["FORECAST_TIME"] = hour.isoformat()
        mock_http.get(
            forecast_url(bbox, hour), **(kwargs or {"payload": page(records)})
        )

    async def advance(moment: datetime) -> None:
        freezer.move_to(moment)
        async_fire_time_changed(hass, datetime.now(UTC))
        await hass.async_block_till_done(wait_background_tasks=True)

    return target, respond, advance


async def setup_route(
    hass: HomeAssistant, route_data: dict[str, Any], *, disable_polling: bool = False
) -> tuple[MockConfigEntry, RouteCoordinator]:
    """Load the real parent, six sensors and their coordinator subscriptions."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="public_service",
        data={},
        pref_disable_polling=disable_polling,
        subentries_data=[
            {
                "subentry_type": "route",
                "unique_id": "route:example-route",
                "title": "Public example",
                "data": route_data,
            }
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, next(iter(entry.runtime_data.routes.values()))


def request_count(mock_http: aioresponses) -> int:
    """Count actual requests, including failures."""
    return sum(map(len, mock_http.requests.values()))


@pytest.mark.parametrize(
    "boundary",
    [
        "2026-10-04T15:00:00+00:00",
        "2026-10-05T00:00:00+00:00",
        "2026-10-25T01:00:00+00:00",  # Europe/Oslo daylight-saving transition
    ],
)
async def test_aligned_polling_and_recovery(
    hass: HomeAssistant,
    mock_http: aioresponses,
    route_data: dict[str, Any],
    forecast_clock: Clock,
    freezer: FrozenDateTimeFactory,
    boundary: str,
) -> None:
    """Refresh on boundaries, suppress unchanged states and recover after failures."""
    _, respond, advance = forecast_clock
    target = datetime.fromisoformat(boundary)
    freezer.move_to(target - timedelta(minutes=25))
    respond(target)
    entry, coordinator = await setup_route(hass, route_data)
    time_id = source_entity(hass, "forecast_time")
    await advance(target - timedelta(milliseconds=1))
    assert request_count(mock_http) == 1
    next_target = target + timedelta(hours=1)
    respond(next_target)
    await advance(target + timedelta(seconds=2))
    assert hass.states.get(time_id).state == next_target.isoformat()
    assert request_count(mock_http) == 2
    unchanged = hass.states.get(time_id)
    respond(next_target)
    await advance(target + timedelta(minutes=30, seconds=2))
    assert request_count(mock_http) == 3
    assert hass.states.get(time_id) is unchanged
    final_target = target + timedelta(hours=2)
    respond(final_target, status=503)
    await advance(target + timedelta(hours=1, seconds=2))
    assert hass.states.get(time_id).state == STATE_UNAVAILABLE
    respond(final_target)
    await advance(target + timedelta(hours=1, minutes=30, seconds=2))
    assert hass.states.get(time_id).state == final_target.isoformat()
    assert request_count(mock_http) == 5
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert coordinator._unsub_refresh is None
    await advance(target + timedelta(hours=2, seconds=2))
    assert request_count(mock_http) == 5


async def test_manual_refresh_does_not_shift_boundary(
    hass: HomeAssistant,
    mock_http: aioresponses,
    route_data: dict[str, Any],
    forecast_clock: Clock,
) -> None:
    """A manual update keeps the next automatic poll aligned to the clock."""
    target, respond, advance = forecast_clock
    respond(target)
    _, coordinator = await setup_route(hass, route_data)
    await advance(target - timedelta(minutes=10))
    respond(target)
    await coordinator.async_request_refresh()
    assert request_count(mock_http) == 2
    respond(target + timedelta(hours=1))
    await advance(target + timedelta(seconds=2))
    assert request_count(mock_http) == 3


async def test_retry_after_overrides_clock_boundary(
    hass: HomeAssistant,
    mock_http: aioresponses,
    route_data: dict[str, Any],
    forecast_clock: Clock,
) -> None:
    """A rate limit spanning the half-hour blocks that poll, then alignment resumes."""
    target, respond, advance = forecast_clock
    respond(target)
    await setup_route(hass, route_data)
    next_target = target + timedelta(hours=1)
    respond(next_target, status=429, headers={"Retry-After": "1900"})
    await advance(target + timedelta(seconds=2))
    time_id = source_entity(hass, "forecast_time")
    assert hass.states.get(time_id).state == STATE_UNAVAILABLE
    await advance(target + timedelta(minutes=30, seconds=2))
    assert request_count(mock_http) == 2
    respond(next_target)
    await advance(target + timedelta(seconds=1904))
    assert hass.states.get(time_id).state == next_target.isoformat()
    respond(target + timedelta(hours=2))
    await advance(target + timedelta(hours=1, seconds=2))
    assert request_count(mock_http) == 4


async def test_request_crossing_hour_catches_up(
    hass: HomeAssistant,
    mock_http: aioresponses,
    route_data: dict[str, Any],
    forecasts: list[dict[str, Any]],
    forecast_clock: Clock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A request finishing after rollover does not wait another half-hour."""
    target, respond, advance = forecast_clock
    freezer.move_to(target - timedelta(seconds=2))
    records = deepcopy(forecasts)
    for record in records:
        record["properties"]["FORECAST_TIME"] = target.isoformat()

    def slow_response(*_args: Any, **_kwargs: Any) -> CallbackResult:
        freezer.move_to(target + timedelta(seconds=5))
        return CallbackResult(payload=page(records))

    respond(target, callback=slow_response)
    _, coordinator = await setup_route(hass, route_data)
    assert coordinator.data.forecast_time == target
    respond(target + timedelta(hours=1))
    await advance(target + timedelta(seconds=7))
    assert coordinator.data.forecast_time == target + timedelta(hours=1)
    assert request_count(mock_http) == 2


async def test_disabled_polling(
    hass: HomeAssistant,
    mock_http: aioresponses,
    route_data: dict[str, Any],
    forecast_clock: Clock,
) -> None:
    """HA's system option still disables scheduled network traffic."""
    target, respond, advance = forecast_clock
    respond(target)
    _, coordinator = await setup_route(hass, route_data, disable_polling=True)
    assert coordinator._unsub_refresh is None
    await advance(target + timedelta(hours=1))
    assert request_count(mock_http) == 1
