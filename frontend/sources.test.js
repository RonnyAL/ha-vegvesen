import test from "node:test";
import assert from "node:assert/strict";
import {
  sourceItems,
  sourceRequest,
  sourceSections,
  stationValues,
} from "./sources.js";
import { labels } from "./labels.js";
import { RouteData, validateConfig } from "./data.js";
import { changedConfig, editorConfig } from "./config.js";

test("source families share groups while keeping IDs and failure states independent", () => {
  const source = {
    source_id: "001",
    name: "Source",
    latitude: 0,
    longitude: 0,
  };
  const snapshot = {
    cameras: { status: "ready", items: [{ ...source, orientation: "North" }] },
    weather: { status: "ready", items: [{ ...source, air_temperature: -999 }] },
  };
  const items = sourceItems(snapshot);
  assert.equal(items.length, 2);
  assert.notEqual(items[0].id, items[1].id);
  assert.deepEqual(items[0].coordinates, [0, 0]);
  assert.equal(items[0].name, "Source — North");
  snapshot.cameras.status = "unavailable";
  assert.deepEqual(sourceItems(snapshot), [items[1]]);
  snapshot.weather.status = "loading";
  assert.deepEqual(sourceItems(snapshot), []);
});

test("weather details preserve zero, missing and unusual values and expose observation time", () => {
  const hass = { locale: { language: "en" }, config: { time_zone: "UTC" } };
  const source = { measurement_time: null };
  for (const [value, expected] of [
    [0, "0 °C"],
    [-999.5, "-999.5 °C"],
    [null, "Missing data"],
  ]) {
    source.air_temperature = value;
    assert.deepEqual(stationValues(source, hass, labels.en), [
      ["Air temperature", expected],
      ["Observation time", "Missing data"],
    ]);
  }
  source.air_temperature = 0;
  source.measurement_time = "2026-10-06T12:00:00+02:00";
  hass.config.unit_system = { temperature: "°F" };
  const values = stationValues(source, hass, labels.en);
  assert.equal(values[0][1], "32 °F");
  assert.match(values[1][1], /10:00/);
  assert.equal(source.air_temperature, 0);
});

test("mixed groups expose both kinds and distinguish camera directions and same-name sources", () => {
  const source = { name: "Roadside", latitude: 63, longitude: 10 };
  const items = sourceItems({
    cameras: {
      status: "ready",
      items: [
        { ...source, source_id: "north", orientation: "North" },
        { ...source, source_id: "south", orientation: "South" },
        { ...source, source_id: "other-south", orientation: "South" },
      ],
    },
    weather: {
      status: "ready",
      items: [
        { ...source, source_id: "north", air_temperature: -999 },
        { ...source, source_id: "station-2", air_temperature: 0 },
      ],
    },
  });
  const copy = structuredClone(items);
  const sections = sourceSections(items, labels.en);
  assert.deepEqual(
    sections.map((section) => section.label),
    ["Weather stations (2)", "Road cameras (3)"],
  );
  assert.deepEqual(
    sections.map((section) => section.icon),
    ["mdi:weather-partly-cloudy", "mdi:camera"],
  );
  assert.deepEqual(
    sections[0].items.map((item) => item.detail),
    ["north", "station-2"],
  );
  assert.deepEqual(
    sections[1].items.map((item) => [item.heading, item.detail]),
    [
      ["Roadside", "North"],
      ["Roadside", "South · south"],
      ["Roadside", "South · other-south"],
    ],
  );
  assert.deepEqual(items, copy);
  assert.equal(
    new Set(sections.flatMap((section) => section.items.map((item) => item.id)))
      .size,
    5,
  );
  const weatherOnly = sourceSections(
    items.filter((item) => item.kind === "weather"),
    labels.nb,
  );
  assert.deepEqual(
    weatherOnly.map((section) => section.label),
    ["Værstasjoner (2)"],
  );
  assert.deepEqual(sourceSections([], labels.en), []);
});

test("discovery remains opt-in in the editor with independent, validated ranges", () => {
  const defaults = editorConfig({}, {});
  assert.equal(defaults.show_cameras, false);
  assert.equal(defaults.show_weather, false);
  assert.equal(defaults.camera_distance_m, 250);
  assert.equal(defaults.weather_distance_m, 250);
  for (const [kind, prefix] of [
    ["cameras", "camera"],
    ["weather", "weather"],
  ]) {
    const key = `${prefix}_distance_m`;
    const show = `show_${kind}`;
    const config = { device_id: "route", [show]: true, [key]: 5 };
    assert.deepEqual(validateConfig(config), config);
    assert.deepEqual(changedConfig(config, { [show]: false, [key]: null }), {
      device_id: "route",
      [show]: false,
    });
    for (const distance of [0, -1, 2001, 1.5, "250", NaN])
      assert.throws(() =>
        validateConfig({ device_id: "route", [key]: distance }),
      );
    assert.throws(() => validateConfig({ device_id: "route", [show]: "true" }));
  }
});

test("range and visibility changes resubscribe, stale source replies are ignored", async () => {
  const messages = [],
    callbacks = [],
    seen = [];
  let removed = 0;
  const connection = {
    subscribeMessage: async (callback, message) => {
      callbacks.push(callback);
      messages.push(message);
      return () => {
        removed++;
      };
    },
  };
  const data = new RouteData(
    (value) => seen.push(value),
    () => {},
    () => {},
    sourceRequest,
  );
  const hass = { connected: true, connection };
  const config = { device_id: "route", show_cameras: true };
  await data.update(hass, config);
  await data.update(hass, config);
  assert.equal(messages.length, 1);
  await data.update(hass, {
    ...config,
    camera_distance_m: 10,
    show_weather: true,
  });
  assert.equal(removed, 1);
  assert.equal(messages[1].camera_distance_m, 10);
  callbacks[0]({ data: "stale" });
  callbacks[1]({ data: "current" });
  assert.deepEqual(seen, ["current"]);
  data.stop();
  callbacks[1]({ data: "after removal" });
  assert.deepEqual(seen, ["current"]);
  assert.equal(removed, 2);
});
