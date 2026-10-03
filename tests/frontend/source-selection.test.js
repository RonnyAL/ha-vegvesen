import assert from "node:assert/strict";
import test from "node:test";
import {
  SourceSelection,
  UNCLASSIFIED,
} from "../../custom_components/vegvesen/frontend/source-selector.js";

const options = [
  { value: "01", label: "Weather zero (01)", county: "A", municipality: "One" },
  { value: "02", label: "Weather two (02)", county: "A", municipality: "One" },
  {
    value: "camera_1",
    label: "Camera (camera_1)",
    county: "A",
    municipality: "Two",
  },
  {
    value: "camera_2",
    label: "Camera (camera_2)",
    county: "B",
    municipality: "One",
  },
];

test("only populated counties and municipalities appear; nothing is preselected", () => {
  const selection = new SourceSelection(options);
  assert.deepEqual(selection.counties, ["A", "B"]);
  assert.deepEqual(selection.municipalities, []);
  assert.deepEqual(selection.sources, []);
  assert.equal(selection.value, "");
  selection.setCounty("B");
  assert.deepEqual(selection.municipalities, ["One"]);
  assert.deepEqual(selection.sources, []);
  selection.setMunicipality("One");
  assert.deepEqual(selection.sources, [options[3]]);
});

test("county changes always clear the municipality and source, even a same-name municipality", () => {
  const selection = new SourceSelection(options);
  selection.restore("01");
  selection.setCounty("B");
  assert.equal(selection.county, "B");
  assert.equal(selection.municipality, "");
  assert.equal(selection.value, "");
  assert.deepEqual(selection.sources, []);
});

test("municipality changes clear the source and repopulate within the county", () => {
  const selection = new SourceSelection(options);
  selection.restore("01");
  selection.setMunicipality("Two");
  assert.equal(selection.value, "");
  assert.deepEqual(selection.sources, [options[2]]);
  selection.select("01");
  assert.equal(selection.value, "");
  selection.select("camera_1");
  assert.equal(selection.value, "camera_1");
});

test("clearing a parent disables dependent choices and invalid regions cannot persist", () => {
  const selection = new SourceSelection(options);
  selection.restore("01");
  selection.setMunicipality("");
  assert.deepEqual(selection.sources, []);
  selection.setCounty("Not a county");
  assert.equal(selection.county, "");
  assert.deepEqual(selection.municipalities, []);
  selection.setMunicipality("One");
  assert.equal(selection.municipality, "");
});

test("fresh metadata reevaluates source membership, removal and empty catalogues", () => {
  const selection = new SourceSelection(options);
  selection.restore("01");
  selection.replaceOptions([
    { ...options[0], county: "C", municipality: "Three" },
  ]);
  assert.equal(selection.county, "C");
  assert.equal(selection.municipality, "Three");
  assert.equal(selection.value, "01");
  selection.replaceOptions(options.slice(1));
  assert.equal(selection.value, "");
  assert.equal(selection.county, "");
  selection.replaceOptions([]);
  assert.deepEqual(selection.counties, []);
});

test("unclassified records remain accessible without inventing administrative names", () => {
  const unclassified = {
    value: "new",
    label: "New (new)",
    county: null,
    municipality: null,
  };
  const selection = new SourceSelection([...options, unclassified]);
  assert.ok(selection.counties.includes(UNCLASSIFIED));
  selection.setCounty(UNCLASSIFIED);
  assert.deepEqual(selection.municipalities, [UNCLASSIFIED]);
  selection.setMunicipality(UNCLASSIFIED);
  assert.deepEqual(selection.sources, [unclassified]);
  selection.select("new");
  assert.equal(selection.value, "new");
});

test("each form owns its selection state and all source IDs remain strings", () => {
  const first = new SourceSelection(options);
  const second = new SourceSelection(options);
  first.restore("camera_2");
  second.restore("01");
  first.setCounty("A");
  assert.equal(second.value, "01");
  assert.equal(second.sources[0].label, "Weather zero (01)");
});
