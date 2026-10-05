import test from "node:test";
import assert from "node:assert/strict";
import { cameraSources, nearbyCameras, cameraPicture } from "./cameras.js";
import { validateConfig } from "./data.js";
import { changedConfig, editorConfig } from "./config.js";

const camera = (id, longitude, latitude) => ({
  entity_id: `camera.${id}`,
  state: "idle",
  attributes: {
    source_id: id,
    longitude,
    latitude,
    entity_picture: `/api/camera_proxy/camera.${id}?token=test`,
  },
});

test("only registered, readable Vegvesen cameras with coordinates become markers", () => {
  const valid = camera("renamed", 0, 0);
  const foreign = camera("foreign", 10, 60);
  const missing = camera("missing", null, 60);
  const invalid = camera("invalid", 10, Infinity);
  const hass = { states: {}, entities: {} };
  for (const state of [valid, foreign, missing, invalid]) {
    hass.states[state.entity_id] = state;
    hass.entities[state.entity_id] = { platform: "vegvesen" };
  }
  hass.entities[foreign.entity_id].platform = "other";
  hass.entities["camera.hidden"] = { platform: "vegvesen" };
  assert.deepEqual(cameraSources(hass), [valid]);
  delete hass.states[valid.entity_id];
  assert.deepEqual(cameraSources(hass), []);
});

test("camera range is measured against the route, not forecast segments or map zoom", () => {
  const geometry = {
    type: "LineString",
    coordinates: [
      [10, 60],
      [10.01, 60],
    ],
  };
  const on = camera("on", 10.005, 60);
  const near = camera("near", 10.005, 60.001); // About 111 meters north.
  const far = camera("far", 10.005, 60.01);
  const sources = [on, near, far];
  assert.deepEqual(nearbyCameras(sources, geometry, 10), [on]);
  assert.deepEqual(nearbyCameras(sources, geometry, 250), [on, near]);
  assert.deepEqual(nearbyCameras(sources, null, 250), []);
});

test("disconnected route parts are not joined through unrelated cameras", () => {
  const geometry = {
    type: "MultiLineString",
    coordinates: [
      [
        [10, 60],
        [10.01, 60],
      ],
      [
        [11, 60],
        [11.01, 60],
      ],
    ],
  };
  const gap = camera("gap", 10.5, 60);
  const second = camera("second", 11.005, 60);
  assert.deepEqual(nearbyCameras([gap, second], geometry, 100), [second]);
});

test("camera proximity follows a route crossing the antimeridian", () => {
  const geometry = {
    type: "LineString",
    coordinates: [
      [179.99, 0],
      [-179.99, 0],
    ],
  };
  const near = camera("near", -180, 0);
  const far = camera("far", 0, 0);
  assert.deepEqual(nearbyCameras([near, far], geometry, 100), [near]);
});

test("images use only the selected entity's HA proxy while available", () => {
  const state = camera("one", 10, 60);
  const hass = { hassUrl: (path) => `https://ha.example${path}` };
  assert.equal(
    cameraPicture(state, hass),
    "https://ha.example/api/camera_proxy/camera.one?token=test",
  );
  for (const path of [
    "https://external.example/image",
    "//external.example/image",
    "/api/camera_proxy/camera.other?token=test",
    "/local/image.jpg",
  ]) {
    state.attributes.entity_picture = path;
    assert.equal(cameraPicture(state, hass), undefined);
  }
  for (const status of ["unavailable", "unknown"]) {
    state.state = status;
    state.attributes.entity_picture = "/api/camera_proxy/camera.one?token=test";
    assert.equal(cameraPicture(state, hass), undefined);
  }
});

test("camera layer is optional with independent, validated proximity settings", () => {
  assert.equal(editorConfig({}, {}).show_cameras, false);
  assert.equal(editorConfig({}, {}).camera_distance_m, 250);
  const config = {
    device_id: "route",
    show_cameras: true,
    camera_distance_m: 5,
  };
  assert.deepEqual(validateConfig(config), config);
  assert.deepEqual(
    changedConfig(config, { show_cameras: false, camera_distance_m: null }),
    { device_id: "route", show_cameras: false },
  );
  for (const camera_distance_m of [0, -1, 2001, 1.5, "250", NaN])
    assert.throws(() =>
      validateConfig({ device_id: "route", camera_distance_m }),
    );
  assert.throws(() =>
    validateConfig({ device_id: "route", show_cameras: "true" }),
  );
});
