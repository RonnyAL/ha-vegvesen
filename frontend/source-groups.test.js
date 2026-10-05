import test from "node:test";
import assert from "node:assert/strict";
import { sourceGroups } from "./source-groups.js";

const item = (id, x, y) => ({ id, coordinates: [x, y] });
const project = ([x, y]) => ({ x, y });
const members = (groups) => groups.map((group) => group.items.map((p) => p.id));

test("coincident sources retain distinct identities in one stable group", () => {
  const sources = [item("camera:north", 10, 60), item("camera:south", 10, 60)];
  const copy = structuredClone(sources);
  const groups = sourceGroups(sources, project);
  assert.deepEqual(members(groups), [["camera:north", "camera:south"]]);
  assert.deepEqual(groups[0].center, { x: 10, y: 60 });
  assert.equal(
    groups[0].id,
    sourceGroups([...sources].reverse(), project)[0].id,
  );
  assert.deepEqual(sources, copy);
});

test("nearby markers group on screen and separate at a closer zoom", () => {
  const sources = [
    item("camera:a", 0, 0),
    item("camera:b", 30, 0),
    item("camera:c", 120, 0),
  ];
  assert.deepEqual(members(sourceGroups(sources, project)), [
    ["camera:a", "camera:b"],
    ["camera:c"],
  ]);
  assert.deepEqual(
    members(sourceGroups(sources, ([x, y]) => ({ x: x * 2, y: y * 2 }))),
    [["camera:a"], ["camera:b"], ["camera:c"]],
  );
  assert.deepEqual(
    members(sourceGroups(sources, ([x, y]) => ({ x: x + 600, y: y - 400 }))),
    [["camera:a", "camera:b"], ["camera:c"]],
  );
});

test("a bridging source joins overlapping groups instead of leaving stacked group buttons", () => {
  const sources = [item("a", 0, 0), item("b", 70, 0), item("c", 35, 0)];
  assert.deepEqual(members(sourceGroups(sources, project)), [["a", "b", "c"]]);
});

test("presentation accepts mixed source kinds without an ownership or fetching model", () => {
  const sources = [
    item("camera:123", 10, 60),
    item("weather_station:123", 10, 60),
  ];
  assert.deepEqual(members(sourceGroups(sources, project)), [
    ["camera:123", "weather_station:123"],
  ]);
  assert.deepEqual(members(sourceGroups(sources.slice(1), project)), [
    ["weather_station:123"],
  ]);
  assert.deepEqual(sourceGroups([], project), []);
});
