"""Requested-hour forecasts through native service calls and mocked HTTP."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from aioresponses import CallbackResult
from homeassistant.components.automation.config import async_validate_config_item
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.script import Script
from homeassistant.util.yaml import load_yaml

from custom_components.vegvesen.const import DOMAIN
from custom_components.vegvesen.route_coordinator import FORECAST_CACHE_SIZE
from custom_components.vegvesen.route_geometry import make_corridor
from custom_components.vegvesen.route_services import forecast_hour

from .helpers import page
from .test_route_polling import request_count, setup_route
from .test_routes import forecast_url, source_entity

if TYPE_CHECKING:
    from aioresponses import aioresponses
    from freezegun.api import FrozenDateTimeFactory
    from homeassistant.core import HomeAssistant


@pytest.fixture
async def action_route(
    hass: HomeAssistant,
    mock_http: aioresponses,
    route_data: dict[str, Any],
    forecasts: list[dict[str, Any]],
    freezer: FrozenDateTimeFactory,
) -> dict[str, Any]:
    """Keep the normal sensor hour separate from later query-only hours."""
    await hass.config.async_set_time_zone("UTC")
    now = datetime(2026, 10, 6, 6, tzinfo=UTC)
    freezer.move_to(now + timedelta(minutes=15))
    route_data["forecast_hours"] = 0

    def records(target: datetime) -> list[dict[str, Any]]:
        result = deepcopy(forecasts)
        for record in result:
            record["properties"]["FORECAST_TIME"] = target.isoformat()
        return result

    bbox = make_corridor(route_data["geometry"], 100).bbox
    mock_http.get(forecast_url(bbox, now), payload=page(records(now)))
    entry, coordinator = await setup_route(hass, route_data)
    device_id = er.async_get(hass).async_get(source_entity(hass, "slip_risk")).device_id

    async def call(**data: Any) -> dict[str, Any]:
        return await hass.services.async_call(
            DOMAIN,
            "get_route_forecasts",
            {"device_id": device_id, **data},
            blocking=True,
            return_response=True,
        )

    return {
        "now": now,
        "bbox": bbox,
        "records": records,
        "call": call,
        "entry": entry,
        "coordinator": coordinator,
        "device_id": device_id,
    }


def respond(
    mock_http: aioresponses, fixture: dict[str, Any], hours: int, **kwargs: Any
) -> datetime:
    """Register a complete requested hour, or a deliberate failure response."""
    target = fixture["now"] + timedelta(hours=hours)
    mock_http.get(
        forecast_url(fixture["bbox"], target),
        **(kwargs or {"payload": page(fixture["records"](target))}),
    )
    return target


async def test_queries_preserve_state_and_share_poll_cache(
    hass: HomeAssistant,
    mock_http: aioresponses,
    action_route: dict[str, Any],
) -> None:
    """New data and summaries are isolated; old callers keep raw cached segments."""
    fixture = action_route
    coordinator = fixture["coordinator"]
    snapshot = coordinator.data
    timer = coordinator._unsub_refresh
    settings = dict(coordinator.subentry.data)
    states = hass.states.async_all()
    legacy = await fixture["call"]()
    current = await fixture["call"](forecast_time=fixture["now"].isoformat())
    assert current["segments"] == legacy["segments"]
    assert current["retrieved_at"] == legacy["retrieved_at"]
    assert current["summary"]["matched_segments"] == 3
    assert request_count(mock_http) == 1
    target = respond(mock_http, fixture, 2)
    result = await fixture["call"](
        forecast_time=(target + timedelta(minutes=35)).isoformat(),
        include_segments=False,
    )
    assert result["forecast_time"] == target.isoformat()
    assert result["requested_time"] == (target + timedelta(minutes=35)).isoformat()
    assert (
        result["retrieved_at"] == (fixture["now"] + timedelta(minutes=15)).isoformat()
    )
    assert "segments" not in result
    assert result["summary"]["matched_segments"] == 3
    repeat = await fixture["call"](forecast_time=target.isoformat())
    assert repeat["summary"] == result["summary"]
    assert request_count(mock_http) == 2
    assert coordinator.data is snapshot
    assert coordinator._unsub_refresh is timer
    assert dict(coordinator.subentry.data) == settings
    assert hass.states.async_all() == states
    # A manual entity refresh still requests new data despite the five-minute cache.
    respond(mock_http, fixture, 0)
    await coordinator.async_refresh()
    assert request_count(mock_http) == 3


async def test_summary_preserves_unusual_zero_null_and_unknown(
    mock_http: aioresponses,
    action_route: dict[str, Any],
) -> None:
    """Summaries report only known source grades and expose gaps separately."""
    target = action_route["now"] + timedelta(hours=1)
    records = action_route["records"](target)
    for record, temperature, condition, slip in zip(
        records,
        [-999.5, 0, None],
        ["IceOrFrost", "FutureCode", None],
        ["high", "FutureGrade", "ErrorOrNoData"],
        strict=True,
    ):
        record["properties"].update(
            ROAD_TEMPERATURE=temperature, ROAD_CONDITION=condition, SLIP_RISK=slip
        )
    respond(mock_http, action_route, 1, payload=page(records))
    result = await action_route["call"](forecast_time=target.isoformat())
    assert [s["properties"]["ROAD_TEMPERATURE"] for s in result["segments"]] == [
        -999.5,
        0,
        None,
    ]
    assert result["summary"] == {
        "matched_segments": 3,
        "road_condition": {
            "source_categories": {"IceOrFrost": 1, "FutureCode": 1},
            "missing_segments": 1,
            "unrecognized_segments": 1,
        },
        "slipperiness": {
            "source_categories": {"high": 1, "FutureGrade": 1, "ErrorOrNoData": 1},
            "missing_segments": 1,
            "unrecognized_segments": 1,
            "highest_known": "high",
        },
        "road_temperature": {
            "minimum": -999.5,
            "maximum": 0,
            "unit": "°C",
            "missing_segments": 1,
        },
    }


@pytest.mark.parametrize("hours", [-1, 25])
async def test_time_limits_before_network(
    mock_http: aioresponses,
    action_route: dict[str, Any],
    hours: int,
) -> None:
    """The UI limit does not become an upstream availability claim."""
    target = action_route["now"] + timedelta(hours=hours)
    with pytest.raises(ServiceValidationError) as error:
        await action_route["call"](forecast_time=target.isoformat())
    assert error.value.translation_key == "forecast_time_out_of_range"
    assert request_count(mock_http) == 1


async def test_empty_future_is_cached_and_recovers(
    mock_http: aioresponses,
    action_route: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    """An empty snapshot is valid absence, not failure or zero temperature."""
    target = respond(mock_http, action_route, 24, payload=page([]))
    result = await action_route["call"](forecast_time=target.isoformat())
    assert result["segments"] == []
    assert result["summary"]["matched_segments"] == 0
    assert result["summary"]["slipperiness"]["highest_known"] is None
    assert result["summary"]["road_temperature"]["minimum"] is None
    assert result["summary"]["road_condition"]["source_categories"] == {}
    assert await action_route["call"](forecast_time=target.isoformat()) == result
    assert request_count(mock_http) == 2
    freezer.tick(timedelta(minutes=5, seconds=1))
    respond(mock_http, action_route, 24)
    result = await action_route["call"](forecast_time=target.isoformat())
    assert result["summary"]["matched_segments"] == 3
    assert request_count(mock_http) == 3


@pytest.mark.parametrize("failure", ["http", "later_page", "wrong_hour"])
async def test_failure_is_not_a_partial_or_cached_success(
    mock_http: aioresponses,
    action_route: dict[str, Any],
    failure: str,
) -> None:
    """Atomic responses and immediate retries also cover eagerly completed failures."""
    fixture = action_route
    target = fixture["now"] + timedelta(hours=1)
    records = fixture["records"](target)
    if failure == "http":
        respond(mock_http, fixture, 1, status=503)
    elif failure == "wrong_hour":
        respond(mock_http, fixture, 1, payload=page(fixture["records"](fixture["now"])))
    else:
        url = forecast_url(fixture["bbox"], target, 1)
        respond(
            mock_http, fixture, 1, payload=page(records[:1], matched=2, next_url=url)
        )
        mock_http.get(url, status=503)
    snapshot = fixture["coordinator"].data
    with pytest.raises(HomeAssistantError) as error:
        await fixture["call"](forecast_time=target.isoformat())
    assert error.value.translation_key == "forecast_request_failed"
    assert fixture["coordinator"].last_update_success
    assert fixture["coordinator"].data is snapshot
    respond(mock_http, fixture, 1)
    result = await fixture["call"](forecast_time=target.isoformat())
    assert len(result["segments"]) == 3


async def test_concurrent_requests_and_cancelled_caller(
    hass: HomeAssistant,
    mock_http: aioresponses,
    action_route: dict[str, Any],
) -> None:
    """One cancelled automation must not cancel another's shared request."""
    entered, release = asyncio.Event(), asyncio.Event()
    target = action_route["now"] + timedelta(hours=2)

    async def held(*_args: Any, **_kwargs: Any) -> CallbackResult:
        entered.set()
        await release.wait()
        return CallbackResult(payload=page(action_route["records"](target)))

    respond(mock_http, action_route, 2, callback=held)
    first = hass.async_create_task(
        action_route["call"](forecast_time=target.isoformat())
    )
    await asyncio.wait_for(entered.wait(), 2)
    second = hass.async_create_task(
        action_route["call"](forecast_time=target.isoformat())
    )
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    result = await asyncio.wait_for(second, 2)
    assert result["summary"]["matched_segments"] == 3
    assert request_count(mock_http) == 2
    assert await action_route["call"](forecast_time=target.isoformat()) == result
    assert request_count(mock_http) == 2


async def test_shared_failure_and_recovery(
    hass: HomeAssistant,
    mock_http: aioresponses,
    action_route: dict[str, Any],
) -> None:
    """Concurrent failures coalesce as well, without a cached error on retry."""
    entered, release = asyncio.Event(), asyncio.Event()

    async def held(*_args: Any, **_kwargs: Any) -> CallbackResult:
        entered.set()
        await release.wait()
        return CallbackResult(status=503, reason="Service Unavailable")

    target = respond(mock_http, action_route, 1, callback=held)
    calls = [
        hass.async_create_task(action_route["call"](forecast_time=target.isoformat()))
        for _ in range(3)
    ]
    await asyncio.wait_for(entered.wait(), 2)
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.wait_for(asyncio.gather(*calls, return_exceptions=True), 2)
    assert all(isinstance(result, HomeAssistantError) for result in results), results
    assert request_count(mock_http) == 2
    respond(mock_http, action_route, 1)
    assert (await action_route["call"](forecast_time=target.isoformat()))["segments"]
    assert request_count(mock_http) == 3


async def test_cache_eviction_and_timeout(
    hass: HomeAssistant,
    mock_http: aioresponses,
    action_route: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Memory stays bounded and one slow request cannot wait indefinitely."""
    for hours in range(1, FORECAST_CACHE_SIZE + 2):
        target = respond(mock_http, action_route, hours)
        await action_route["call"](forecast_time=target.isoformat())
    first = respond(mock_http, action_route, 1)
    await action_route["call"](forecast_time=first.isoformat())
    assert request_count(mock_http) == FORECAST_CACHE_SIZE + 3

    entered = asyncio.Event()

    async def stalled(*_args: Any, **_kwargs: Any) -> CallbackResult:
        if entered.is_set():
            return CallbackResult(payload=page(action_route["records"](target)))
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    target = respond(mock_http, action_route, 10, callback=stalled)
    call = hass.async_create_task(
        action_route["call"](forecast_time=target.isoformat())
    )
    await asyncio.wait_for(entered.wait(), 2)
    freezer.tick(timedelta(seconds=41))
    with pytest.raises(HomeAssistantError) as error:
        await call
    assert error.value.translation_key == "forecast_request_failed"
    assert (await action_route["call"](forecast_time=target.isoformat()))["segments"]


async def test_rate_limit_applies_to_actions_and_polling(
    mock_http: aioresponses,
    action_route: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Keep the existing endpoint-wide Retry-After cooldown, and allow recovery."""
    target = respond(
        mock_http, action_route, 1, status=429, headers={"Retry-After": "120"}
    )
    with pytest.raises(HomeAssistantError) as error:
        await action_route["call"](forecast_time=target.isoformat())
    assert error.value.translation_key == "forecast_rate_limited"
    assert error.value.translation_placeholders == {"seconds": "120"}
    await action_route["coordinator"].async_refresh()
    assert not action_route["coordinator"].last_update_success
    assert request_count(mock_http) == 2
    freezer.tick(timedelta(seconds=121))
    respond(mock_http, action_route, 1)
    result = await action_route["call"](forecast_time=target.isoformat())
    assert result["summary"]["matched_segments"] == 3
    # An explicit future-hour success does not reset a failed sensor coordinator.
    assert not action_route["coordinator"].last_update_success


async def test_unload_cancels_queries_and_discards_cache(
    hass: HomeAssistant,
    mock_http: aioresponses,
    action_route: dict[str, Any],
) -> None:
    """Entry ownership cancels shared background I/O and blocks stale results."""
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def held(*_args: Any, **_kwargs: Any) -> CallbackResult:
        if cancelled.is_set():
            return CallbackResult(payload=page(action_route["records"](target)))
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        raise AssertionError("unreachable")

    target = respond(mock_http, action_route, 1, callback=held)
    call = hass.async_create_task(
        action_route["call"](forecast_time=target.isoformat())
    )
    await asyncio.wait_for(entered.wait(), 2)
    assert await hass.config_entries.async_unload(action_route["entry"].entry_id)
    with pytest.raises(ServiceValidationError):
        await asyncio.wait_for(call, 2)
    assert cancelled.is_set()
    coordinator = action_route["coordinator"]
    assert not coordinator._forecast_cache
    assert not coordinator._forecast_tasks
    respond(mock_http, action_route, 0)
    assert await hass.config_entries.async_setup(action_route["entry"].entry_id)
    result = await action_route["call"](forecast_time=target.isoformat())
    assert result["summary"]["matched_segments"] == 3
    assert request_count(mock_http) == 4


async def test_device_removal_during_query(
    hass: HomeAssistant,
    mock_http: aioresponses,
    action_route: dict[str, Any],
) -> None:
    """Recheck the public selection after I/O instead of leaking removed-route data."""
    entered, release = asyncio.Event(), asyncio.Event()
    target = action_route["now"] + timedelta(hours=1)

    async def held(*_args: Any, **_kwargs: Any) -> CallbackResult:
        entered.set()
        await release.wait()
        return CallbackResult(payload=page(action_route["records"](target)))

    respond(mock_http, action_route, 1, callback=held)
    call = hass.async_create_task(
        action_route["call"](forecast_time=target.isoformat())
    )
    await asyncio.wait_for(entered.wait(), 2)
    dr.async_get(hass).async_remove_device(action_route["device_id"])
    release.set()
    with pytest.raises(ServiceValidationError):
        await asyncio.wait_for(call, 2)


async def test_timezone_and_dst_selection(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Native local dates and explicit offsets select unambiguous UTC query hours."""
    await hass.config.async_set_time_zone("Europe/Oslo")
    freezer.move_to("2026-10-24T23:15:00+00:00")
    assert forecast_hour("2026-10-25 02:30:00")[1] == datetime(
        2026, 10, 25, 0, tzinfo=UTC
    )
    assert forecast_hour("2026-10-25T02:30:00+02:00")[1].hour == 0
    assert forecast_hour("2026-10-25T02:30:00+01:00")[1].hour == 1


@pytest.mark.parametrize("outcome", ["mixed", "empty", "failure"])
async def test_briefing_example(
    hass: HomeAssistant,
    mock_http: aioresponses,
    action_route: dict[str, Any],
    outcome: str,
) -> None:
    """Execute the documented automation with HA templates and response variables."""
    automation = load_yaml(
        str(Path(__file__).parents[1] / "examples/route_forecast_briefing.yaml")
    )
    automation["actions"][0]["data"]["device_id"] = action_route["device_id"]
    target = action_route["now"] + timedelta(hours=1)
    records = action_route["records"](target)
    for record, temperature, condition, slip in zip(
        records,
        [0, None, None],
        ["IceOrFrost", "FutureCode", None],
        ["high", "FutureGrade", None],
        strict=True,
    ):
        record["properties"].update(
            ROAD_TEMPERATURE=temperature, ROAD_CONDITION=condition, SLIP_RISK=slip
        )
    kwargs = (
        {"status": 503}
        if outcome == "failure"
        else {"payload": page([] if outcome == "empty" else records)}
    )
    respond(mock_http, action_route, 1, **kwargs)
    messages = []
    hass.services.async_register(
        "persistent_notification", "create", lambda call: messages.append(call.data)
    )
    config = await async_validate_config_item(hass, "automation", automation)
    script = Script(hass, config["actions"], "Briefing example", DOMAIN)
    await script.async_run()
    assert len(messages) == 1
    message = " ".join(messages[0]["message"].split())
    if outcome == "failure":
        assert "request failed" in message
    elif outcome == "empty":
        assert "No matching forecast" in message
    else:
        assert "Highest known slipperiness: high" in message
        assert "Ice or frost: 1 segments" in message
        assert "Unrecognized condition (FutureCode): 1 segments" in message
        assert "Road temperature: 0 to 0 °C" in message
        assert (
            "Missing values — condition: 1, slipperiness: 1, temperature: 2" in message
        )
        assert "Unrecognized categories — condition: 1, slipperiness: 1" in message
