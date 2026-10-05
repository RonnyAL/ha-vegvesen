// Build without network access; only public map tiles/fonts are fetched at runtime.
import { build } from "esbuild";
import { osm } from "@versatiles/style";
import { readFile, mkdir, writeFile, readdir } from "node:fs/promises";
import { resolve } from "node:path";
import { MAP_STYLES } from "./config.js";
import { HA_MAP_COLORS, HA_MAP_COLORS_DARK } from "./ha-map-palette.js";

const directory = "custom_components/vegvesen/frontend";
const styles = {};
for (const preset of MAP_STYLES)
  for (const dark of [false, true]) {
    const base = preset === "default" ? "colorful" : preset;
    const theme = base + (dark ? "-dark" : "");
    const style = osm({
      theme,
      projection: "mercator",
      ...(preset === "default"
        ? { colors: dark ? HA_MAP_COLORS_DARK : HA_MAP_COLORS }
        : {}),
    });
    style.metadata = {
      "vegvesen:preset": preset,
      "vegvesen:mode": dark ? "dark" : "light",
    };
    style.sources["versatiles-shortbread"] = {
      type: "vector",
      url: "https://vector.openstreetmap.org/shortbread_v1/tilejson.json",
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    };
    style.glyphs =
      "https://vector.openstreetmap.org/styles/shortbread/fonts/{fontstack}/{range}.pbf";
    // A quiet road map needs labels, not POI icons or extra sprite downloads.
    delete style.sprite;
    for (const layer of style.layers) {
      if (layer.layout) {
        for (const key of Object.keys(layer.layout)) {
          if (key.startsWith("icon-")) delete layer.layout[key];
        }
      }
      if (layer.paint) {
        delete layer.paint["fill-pattern"];
        for (const key of Object.keys(layer.paint)) {
          if (key.startsWith("icon-")) delete layer.paint[key];
        }
      }
    }
    style.layers = style.layers.filter(
      (layer) =>
        layer.type !== "symbol" || layer.layout?.["text-field"] !== undefined,
    );
    styles[`${preset}-${dark ? "dark" : "light"}`] = style;
  }

const result = await build({
  entryPoints: ["frontend/route-map-card.js"],
  outfile: `${directory}/vegvesen-route-map.js`,
  bundle: true,
  format: "esm",
  target: "es2022",
  minify: true,
  legalComments: "inline",
  loader: { ".css": "text" },
  write: false,
});
const licenses = [
  [
    "Home Assistant frontend 20260930.0 (default map palette; Home Assistant contributors)",
    "frontend/LICENSE.home-assistant.md",
  ],
  [
    "MapLibre GL JS 6.12.0 (including bundled dependencies)",
    "node_modules/maplibre-gl/LICENSE.txt",
  ],
  [
    "VersaTiles Style 6.1.1 (generated map styles)",
    "node_modules/@versatiles/style/LICENSE.md",
  ],
];
const worker = await build({
  entryPoints: ["node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs"],
  outfile: `${directory}/maplibre-gl-worker.js`,
  bundle: true,
  format: "esm",
  target: "es2022",
  minify: true,
  legalComments: "inline",
  write: false,
});
let notice = "# Frontend third-party licenses\n\n";
for (const [name, path] of licenses)
  notice += `## ${name}\n\n${await readFile(path, "utf8")}\n`;
const visited = new Set(["maplibre-gl"]);
async function dependencyLicenses(name) {
  const directory = `node_modules/${name}`;
  const manifest = JSON.parse(
    await readFile(`${directory}/package.json`, "utf8"),
  );
  for (const dependency of Object.keys(manifest.dependencies ?? {}).sort()) {
    if (visited.has(dependency)) continue;
    visited.add(dependency);
    const root = `node_modules/${dependency}`;
    const license = (await readdir(root)).find((file) =>
      /^licen[sc]e(?:\.md|\.txt)?$/i.test(file),
    );
    if (!license && dependency !== "murmurhash-js")
      throw Error(`Missing license for ${dependency}`);
    const text = await readFile(`${root}/${license ?? "README.md"}`, "utf8");
    notice += `## ${dependency}\n\n${license ? text : text.slice(text.indexOf("## License (MIT)"))}\n`;
    await dependencyLicenses(dependency);
  }
}
await dependencyLicenses("maplibre-gl");
const outputs = [
  ...Object.entries(styles).map(([name, style]) => [
    resolve(directory, "styles", `${name}.json`),
    Buffer.from(JSON.stringify(style) + "\n"),
  ]),
  ...[...result.outputFiles, ...worker.outputFiles].map((file) => [
    file.path,
    file.contents,
  ]),
  [resolve(directory, "LICENSES.md"), Buffer.from(notice.trimEnd() + "\n")],
];
if (!process.argv.includes("--check"))
  await mkdir(`${directory}/styles`, { recursive: true });
for (const [path, content] of outputs) {
  if (process.argv.includes("--check")) {
    if (!Buffer.from(await readFile(path)).equals(Buffer.from(content)))
      throw Error(`Rebuild ${path} with npm run build`);
  } else await writeFile(path, content);
}
console.log(
  process.argv.includes("--check")
    ? "Frontend bundle matches locked sources"
    : "Built route map card",
);
