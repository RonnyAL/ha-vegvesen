"""Test entity behavior, refresh atomicity and the real entry lifecycle."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from aioresponses import CallbackResult, aioresponses
from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.vegvesen.const import (
    CONF_STATION_ID,
    DOMAIN,
    SUBENTRY_WEATHER_STATION,
    WEATHER_UPDATE_INTERVAL,
)

from .helpers import page, weather_url

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def entity_id(hass: HomeAssistant, station_id: str, key: str) -> str:
    """Locate an entity by stable identity, independent of its translated name."""
    result = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"weather_station:{station_id}:{key}"
    )
    assert result is not None
    return result


async def setup_entry(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
) -> None:
    """Set up actual platforms using a mocked HTTP response."""
    config_entry.add_to_hass(hass)
    mock_http.get(weather_url(("1629006", "1629013")), payload=page(features[:2]))
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_devices_entities_and_unload(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    freezer: Any,
) -> None:
    """Register source devices/subentries, then stop all polling on unload."""
    await setup_entry(hass, config_entry, mock_http, features)
    coordinator = config_entry.runtime_data.weather
    assert coordinator.update_interval == WEATHER_UPDATE_INTERVAL
    assert (
        len(
            er.async_entries_for_config_entry(er.async_get(hass), config_entry.entry_id)
        )
        == 4
    )
    for subentry in config_entry.subentries.values():
        station_id = subentry.data[CONF_STATION_ID]
        temperature_id = entity_id(hass, station_id, "air_temperature")
        registered = er.async_get(hass).async_get(temperature_id)
        assert registered.config_subentry_id == subentry.subentry_id
        device = dr.async_get(hass).async_get(registered.device_id)
        assert device.identifiers == {(DOMAIN, f"weather_station:{station_id}")}
        state = hass.states.get(temperature_id)
        source = next(
            f for f in features if f["properties"]["REFERENCE_ID"] == station_id
        )
        assert float(state.state) == source["properties"]["AIR_TEMPERATURE"]
        assert state.attributes["unit_of_measurement"] == "°C"
        assert state.attributes["state_class"] == "measurement"
        assert state.attributes["attribution"] == "Data provided by Statens vegvesen"
        observed = hass.states.get(entity_id(hass, station_id, "measurement_time"))
        assert datetime.fromisoformat(observed.state) == datetime.fromisoformat(
            source["properties"]["MEASUREMENT_TIME"]
        )

    session = async_get_clientsession(hass)
    requests = sum(len(values) for values in mock_http.requests.values())
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED
    assert coordinator._shutdown_requested
    assert coordinator._listeners == {}
    assert coordinator._unsub_refresh is None
    assert config_entry.update_listeners == []
    assert not session.closed
    assert hass.states.get(temperature_id).state == STATE_UNAVAILABLE
    freezer.tick(timedelta(minutes=20))
    async_fire_time_changed(hass, datetime.now(UTC))
    await hass.async_block_till_done()
    assert sum(len(values) for values in mock_http.requests.values()) == requests


async def test_bokmal_names_and_subentry_actions(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
) -> None:
    """HA loads Bokmål names/actions while source-based identities stay intact."""
    hass.config.language = "nb"
    await setup_entry(hass, config_entry, mock_http, features)
    temperature_id = entity_id(hass, "1629006", "air_temperature")
    assert hass.states.get(temperature_id).name == "Fv 714 Våvatnet Lufttemperatur"
    observed_id = entity_id(hass, "1629006", "measurement_time")
    assert hass.states.get(observed_id).name == "Fv 714 Våvatnet Observasjonstid"
    registered = er.async_get(hass).async_get(temperature_id)
    assert registered.unique_id == "weather_station:1629006:air_temperature"
    translations = await async_get_translations(
        hass, "nb", "config_subentries", {DOMAIN}
    )
    prefix = "component.vegvesen.config_subentries"
    assert translations[f"{prefix}.weather_station.initiate_flow.user"] == (
        "Legg til værstasjoner"
    )
    assert translations[f"{prefix}.camera.initiate_flow.user"] == "Legg til veikameraer"


@pytest.mark.parametrize("temperature", [None, 0, -39.6, 9999])
async def test_null_zero_unusual_values(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    temperature: float | None,
) -> None:
    """Null is unknown; zero and implausible values are faithfully exposed."""
    features[0]["properties"]["AIR_TEMPERATURE"] = temperature
    features[0]["properties"]["MEASUREMENT_TIME"] = None
    await setup_entry(hass, config_entry, mock_http, features)
    state = hass.states.get(entity_id(hass, "1629006", "air_temperature"))
    if temperature is None:
        assert state.state == STATE_UNKNOWN
    else:
        assert float(state.state) == temperature
    assert (
        hass.states.get(entity_id(hass, "1629006", "measurement_time")).state
        == STATE_UNKNOWN
    )
    assert (
        hass.states.get(entity_id(hass, "1629013", "air_temperature")).state
        != STATE_UNAVAILABLE
    )


async def test_failure_atomicity_and_recovery(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
) -> None:
    """A failed later page marks weather unavailable and retains the old snapshot."""
    await setup_entry(hass, config_entry, mock_http, features)
    coordinator = config_entry.runtime_data.weather
    previous = coordinator.data
    changed = deepcopy(features[:1])
    changed[0]["properties"]["AIR_TEMPERATURE"] = 500
    ids = ("1629006", "1629013")
    next_url = weather_url(ids, 1)
    mock_http.get(weather_url(ids), payload=page(changed, matched=2, next_url=next_url))
    mock_http.get(next_url, status=503)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert not coordinator.last_update_success
    assert coordinator.data is previous
    for station_id in ids:
        for key in ("air_temperature", "measurement_time"):
            assert (
                hass.states.get(entity_id(hass, station_id, key)).state
                == STATE_UNAVAILABLE
            )
    mock_http.get(weather_url(ids), payload=page(features[:2]))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.last_update_success
    assert (
        float(hass.states.get(entity_id(hass, "1629006", "air_temperature")).state)
        == features[0]["properties"]["AIR_TEMPERATURE"]
    )


async def test_absence_and_return(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
) -> None:
    """A complete snapshot can omit one station without affecting the other."""
    await setup_entry(hass, config_entry, mock_http, features)
    ids = ("1629006", "1629013")
    mock_http.get(weather_url(ids), payload=page(features[1:2]))
    await config_entry.runtime_data.weather.async_refresh()
    await hass.async_block_till_done()
    assert config_entry.runtime_data.weather.last_update_success
    assert (
        hass.states.get(entity_id(hass, "1629006", "air_temperature")).state
        == STATE_UNAVAILABLE
    )
    assert (
        hass.states.get(entity_id(hass, "1629013", "air_temperature")).state
        != STATE_UNAVAILABLE
    )
    mock_http.get(weather_url(ids), payload=page(features[:2]))
    await config_entry.runtime_data.weather.async_refresh()
    await hass.async_block_till_done()
    assert (
        hass.states.get(entity_id(hass, "1629006", "air_temperature")).state
        != STATE_UNAVAILABLE
    )


async def test_initial_failure_and_retry(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    freezer: Any,
) -> None:
    """HA schedules setup retry and later recovers without replacing identities."""
    config_entry.add_to_hass(hass)
    ids = ("1629006", "1629013")
    mock_http.get(weather_url(ids), payload=page(features[:1], matched=2))
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    mock_http.get(weather_url(ids), payload=page(features[:2]))
    freezer.tick(timedelta(seconds=15))
    async_fire_time_changed(hass, datetime.now(UTC))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(entity_id(hass, "1629006", "air_temperature")) is not None


async def test_polling_and_retry_after(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    freezer: Any,
) -> None:
    """Poll at ten minutes and honor rate-limit recovery without a reauth flow."""
    await setup_entry(hass, config_entry, mock_http, features)
    url = weather_url(("1629006", "1629013"))
    mock_http.get(url, status=429, headers={"Retry-After": "120"})
    freezer.tick(timedelta(minutes=10, seconds=1))
    async_fire_time_changed(hass, datetime.now(UTC))
    await hass.async_block_till_done()
    assert not config_entry.runtime_data.weather.last_update_success
    assert config_entry.runtime_data.weather.last_exception.retry_after == 120
    assert hass.config_entries.flow.async_progress() == []
    mock_http.get(url, payload=page(features[:2]))
    freezer.tick(timedelta(seconds=121))
    async_fire_time_changed(hass, datetime.now(UTC))
    await hass.async_block_till_done()
    assert config_entry.runtime_data.weather.last_update_success


async def test_selection_add_remove_reload(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
) -> None:
    """Selection changes replace polling resources and retain existing identities."""
    await setup_entry(hass, config_entry, mock_http, features)
    old_coordinator = config_entry.runtime_data.weather
    old_entity_id = entity_id(hass, "1629006", "air_temperature")
    old_device = er.async_get(hass).async_get(old_entity_id).device_id
    mock_http.get(
        weather_url(("1629004", "1629006", "1629013")), payload=page(features)
    )
    additional = ConfigSubentry(
        data={CONF_STATION_ID: "1629004"},
        subentry_type=SUBENTRY_WEATHER_STATION,
        title="Fv 65 Bye (1629004)",
        unique_id="weather_station:1629004",
    )
    hass.config_entries.async_add_subentry(config_entry, additional)
    await hass.async_block_till_done()
    assert old_coordinator._shutdown_requested
    assert entity_id(hass, "1629006", "air_temperature") == old_entity_id
    assert er.async_get(hass).async_get(old_entity_id).device_id == old_device
    assert (
        float(hass.states.get(entity_id(hass, "1629004", "air_temperature")).state)
        == -39.6
    )

    mock_http.get(weather_url(("1629006", "1629013")), payload=page(features[:2]))
    hass.config_entries.async_remove_subentry(config_entry, additional.subentry_id)
    await hass.async_block_till_done()
    assert len(config_entry.runtime_data.weather.station_ids) == 2
    assert (
        len(
            er.async_entries_for_config_entry(er.async_get(hass), config_entry.entry_id)
        )
        == 4
    )
    assert (
        er.async_get(hass).async_get_entity_id(
            "sensor", DOMAIN, "weather_station:1629004:air_temperature"
        )
        is None
    )


async def test_unload_inflight_poll(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
    freezer: Any,
) -> None:
    """Entry unloading cancels an in-flight scheduled network request."""
    await setup_entry(hass, config_entry, mock_http, features)
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def pending(*_: Any, **__: Any) -> CallbackResult:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return CallbackResult(payload=page(features[:2]))

    mock_http.get(weather_url(("1629006", "1629013")), callback=pending)
    freezer.tick(timedelta(minutes=10, seconds=1))
    async_fire_time_changed(hass, datetime.now(UTC))
    await asyncio.wait_for(started.wait(), timeout=2)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert cancelled.is_set()


async def test_empty_parent_does_not_poll(
    hass: HomeAssistant,
    mock_http: aioresponses,
    freezer: Any,
) -> None:
    """Removing the last selection leaves a valid parent without HTTP polling."""
    entry = MockConfigEntry(domain=DOMAIN, title="Statens vegvesen", subentries_data=[])
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.weather.data == {}
    assert entry.runtime_data.weather._unsub_refresh is None
    freezer.tick(timedelta(minutes=20))
    async_fire_time_changed(hass, datetime.now(UTC))
    await hass.async_block_till_done()
    assert not mock_http.requests
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_initially_absent_station(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_http: aioresponses,
    features: list[dict[str, Any]],
) -> None:
    """Create stable unavailable entities when a selected source is absent at setup."""
    await setup_entry(hass, config_entry, mock_http, features[1:2])
    missing = entity_id(hass, "1629006", "air_temperature")
    assert hass.states.get(missing).state == STATE_UNAVAILABLE
    assert er.async_get(hass).async_get(missing).device_id is not None
    assert (
        hass.states.get(entity_id(hass, "1629013", "air_temperature")).state
        != STATE_UNAVAILABLE
    )
