import test from "node:test";
import assert from "node:assert/strict";
import {
  RouteData,
  bounds,
  color,
  displayGeometry,
  sourceLabel,
  validateConfig,
} from "./data.js";
import { labels } from "./labels.js";

const state = (revision = "1", status = "2026-10-04T12:00:00Z") => ({
  connected: true,
  states: { "image.route": { state: status, last_updated: revision } },
});

test("requests follow image updates, not unrelated HA states; disconnect/recovery", async () => {
  let calls = 0;
  const snapshots = [],
    errors = [];
  let resets = 0;
  const data = new RouteData(
    (value) => snapshots.push(value),
    (error) => errors.push(error),
    () => resets++,
  );
  const hass = {
    ...state(),
    callWS: async (request) => {
      calls++;
      assert.deepEqual(request, {
        type: "vegvesen/route_map",
        entity_id: "image.route",
      });
      return { name: "Public route", segments: [] };
    },
  };
  await data.update(hass, "image.route");
  await data.update({ ...hass }, "image.route");
  assert.equal(calls, 1);
  await data.update({ ...hass, ...state("2") }, "image.route");
  await data.update({ ...hass, connected: false }, "image.route");
  assert.equal(resets, 1);
  assert.deepEqual(errors, ["disconnected"]);
  await data.update(hass, "image.route");
  assert.equal(calls, 3);
  assert.equal(snapshots.length, 3);
  await data.update({ ...hass, ...state("3", "unavailable") }, "image.route");
  assert.equal(calls, 3);
  assert.equal(errors.at(-1), "unavailable");
});

test("late responses cannot restore stale forecasts after failure or card removal", async () => {
  let resolve;
  const snapshots = [];
  const data = new RouteData(
    (value) => snapshots.push(value),
    () => {},
    () => {},
  );
  const hass = {
    ...state(),
    callWS: () =>
      new Promise((done) => {
        resolve = done;
      }),
  };
  const pending = data.update(hass, "image.route");
  await data.update({ ...hass, ...state("2", "unavailable") }, "image.route");
  resolve("stale");
  await pending;
  assert.deepEqual(snapshots, []);
  const second = data.update(hass, "image.route");
  data.stop();
  resolve("removed");
  await second;
  assert.deepEqual(snapshots, []);
});

test("backend errors are handled, retry is explicit, and renamed entities are accepted", async () => {
  const errors = [];
  const data = new RouteData(
    () => {},
    (error) => errors.push(error),
    () => {},
  );
  const hass = {
    ...state(),
    callWS: async () => {
      throw { code: "unknown_command" };
    },
  };
  await data.update(hass, "image.route");
  assert.deepEqual(errors, ["upgrade"]);
  data.stop();
  await data.update(
    {
      ...hass,
      callWS: async () => {
        throw { code: "unavailable" };
      },
    },
    "image.route",
  );
  assert.equal(errors.at(-1), "unavailable");
  assert.equal(
    validateConfig({ entity: "image.renamed" }).entity,
    "image.renamed",
  );
});

test("source category colors and translations do not assign meaning to unknown codes", () => {
  assert.equal(color("IceOrFrost"), "#e69f00");
  assert.equal(color("NewSourceCode"), "#777777");
  assert.equal(color(null), "#777777");
  assert.equal(color("__proto__"), "#777777");
  assert.equal(sourceLabel(labels.en, "__proto__"), "__proto__");
  assert.equal(sourceLabel(labels.en, "fit"), "fit");
  assert.equal(sourceLabel(labels.nb, "low"), "low");
  assert.equal(sourceLabel(labels.nb, "low", "slip"), "Lav");
  assert.deepEqual(
    Object.keys(labels.nb).sort(),
    Object.keys(labels.en).sort(),
  );
});

test("route fit retains disconnected geometry and handles the antimeridian", () => {
  const geometry = {
    type: "MultiLineString",
    coordinates: [
      [
        [179.9, 60],
        [-179.9, 60],
      ],
      [
        [-179.8, 61],
        [-179.7, 61],
      ],
    ],
  };
  const before = structuredClone(geometry);
  const extent = bounds(geometry);
  assert.ok(extent[1][0] - extent[0][0] < 1);
  assert.deepEqual(geometry, before);
  const displayed = displayGeometry(geometry);
  assert.equal(displayed.coordinates.length, 2);
  assert.ok(
    Math.abs(displayed.coordinates[0][1][0] - displayed.coordinates[0][0][0]) <
      1,
  );
  assert.throws(() => validateConfig({ entity: "sensor.route" }));
  assert.throws(() => validateConfig({ entity: "image.route", height: 0 }));
  assert.throws(() =>
    validateConfig({
      entity: "image.route",
      map_style_url: "javascript:alert(1)",
    }),
  );
});

test("long routes fit without expanding coordinates into function arguments", () => {
  const geometry = {
    type: "LineString",
    coordinates: Array.from({ length: 200000 }, (_, i) => [
      10 + i / 1000000,
      60,
    ]),
  };
  assert.ok(bounds(geometry)[1][0] > 10.19);
});
