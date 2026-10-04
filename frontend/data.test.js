import test from "node:test";
import assert from "node:assert/strict";
import {
  RouteData,
  category,
  highlighted,
  selectedBounds,
  bounds,
  color,
  displayGeometry,
  sourceLabel,
  validateConfig,
} from "./data.js";
import { labels } from "./labels.js";

test("subscriptions update unchanged summaries, handle failures and recover without polling", async () => {
  const snapshots = [],
    errors = [];
  let listener,
    calls = 0,
    removed = 0;
  const data = new RouteData(
    (value) => snapshots.push(value),
    (error) => errors.push(error),
    () => {},
  );
  const hass = {
    connected: true,
    states: {},
    connection: {
      subscribeMessage: async (callback, request) => {
        calls++;
        listener = callback;
        assert.equal(request.type, "vegvesen/subscribe_route_map");
        assert.equal(request.entity_id, "sensor.route");
        return async () => removed++;
      },
    },
  };
  await data.update(hass, "sensor.route");
  listener({ data: { summary: "high", segments: [1] } });
  await data.update(
    { ...hass, states: { unrelated: { state: "on" } } },
    "sensor.route",
  );
  listener({ data: { summary: "high", segments: [2] } });
  assert.equal(calls, 1);
  assert.equal(snapshots.length, 2);
  listener({ error: "unavailable" });
  listener({ data: { summary: null, segments: [] } });
  assert.equal(errors.at(-1), "unavailable");
  assert.deepEqual(snapshots.at(-1).segments, []);
  await data.update({ ...hass, connected: false }, "sensor.route");
  assert.equal(removed, 1);
  assert.equal(errors.at(-1), "disconnected");
  listener({ data: "stale" });
  assert.equal(snapshots.length, 3);
  await data.update(hass, "sensor.route");
  assert.equal(calls, 2);
  data.stop();
  assert.equal(removed, 2);
});

test("late subscription acknowledgements are cancelled after card removal", async () => {
  let resolve,
    listener,
    removed = 0;
  const snapshots = [];
  const data = new RouteData(
    (value) => snapshots.push(value),
    () => {},
    () => {},
  );
  const hass = {
    connected: true,
    connection: {
      subscribeMessage: (callback) => {
        listener = callback;
        return new Promise((done) => {
          resolve = done;
        });
      },
    },
  };
  const pending = data.update(hass, "sensor.route");
  data.stop();
  listener({ data: "stale" });
  resolve(async () => removed++);
  await pending;
  assert.equal(removed, 1);
  assert.deepEqual(snapshots, []);
});

test("subscription errors are handled and retry is explicit", async () => {
  const errors = [];
  const data = new RouteData(
    () => {},
    (error) => errors.push(error),
    () => {},
  );
  for (const code of [
    "unknown_command",
    "invalid_route",
    "unauthorized",
    "unavailable",
  ]) {
    data.stop();
    const hass = {
      connected: true,
      connection: {
        subscribeMessage: async () => {
          throw { code };
        },
      },
    };
    await data.update(hass, "sensor.renamed");
  }
  assert.deepEqual(errors, [
    "upgrade",
    "invalid_route",
    "unauthorized",
    "unavailable",
  ]);
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
  assert.throws(() => validateConfig({ entity: "image.route" }));
  assert.throws(() => validateConfig({ entity: "sensor.route", height: 0 }));
  assert.throws(() =>
    validateConfig({
      entity: "sensor.route",
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

test("condition and source slipperiness highlights retain codes and fit only selected geometry", () => {
  const segments = [
    {
      properties: { ROAD_CONDITION: "IceOrFrost", SLIP_RISK: "high" },
      geometry: {
        type: "LineString",
        coordinates: [
          [10, 60],
          [11, 60],
        ],
      },
    },
    {
      properties: { ROAD_CONDITION: "NewCode", SLIP_RISK: "low" },
      geometry: {
        type: "LineString",
        coordinates: [
          [15, 60],
          [16, 60],
        ],
      },
    },
    { properties: { SLIP_RISK: null }, geometry: null },
  ];
  const before = structuredClone(segments);
  assert.equal(category(segments[0], "slip"), "high");
  assert.equal(
    highlighted(segments[0], { mode: "condition", code: "IceOrFrost" }),
    true,
  );
  assert.equal(highlighted(segments[1], { mode: "slip", code: "high" }), false);
  const extent = selectedBounds(segments, { mode: "slip", code: "high" });
  assert.ok(Math.abs(extent[1][0] - 11) < 1e-8);
  assert.equal(
    selectedBounds(segments, { mode: "slip", code: null }),
    undefined,
  );
  assert.equal(color("high", "slip"), "#d55e00");
  assert.equal(color("NewCode", "slip"), "#777777");
  assert.deepEqual(segments, before);
});
