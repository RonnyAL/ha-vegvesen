import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { MAP_STYLES } from "./config.js";

test("every packaged style has light/dark palettes and only the intended public map provider", async () => {
  for (const preset of MAP_STYLES) {
    for (const mode of ["light", "dark"]) {
      const style = JSON.parse(
        await readFile(
          new URL(
            `../custom_components/vegvesen/frontend/styles/${preset}-${mode}.json`,
            import.meta.url,
          ),
        ),
      );
      assert.equal(style.version, 8);
      assert.deepEqual(style.metadata, {
        "vegvesen:preset": preset,
        "vegvesen:mode": mode,
      });
      assert.equal(
        style.sources["versatiles-shortbread"].url,
        "https://vector.openstreetmap.org/shortbread_v1/tilejson.json",
      );
      assert.match(
        style.sources["versatiles-shortbread"].attribution,
        /OpenStreetMap/,
      );
      assert.equal(style.sprite, undefined);
      assert(style.layers.some((layer) => layer.type === "symbol"));
      if (preset === "default") {
        assert.equal(
          style.layers.find((layer) => layer.type === "background").paint[
            "background-color"
          ],
          mode === "dark" ? "rgb(25,27,44)" : "rgb(244,239,230)",
        );
      }
    }
  }
});
