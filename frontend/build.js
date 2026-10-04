// Build without network access; only public map tiles/fonts are fetched at runtime.
import { build } from "esbuild";
import { osm } from "@versatiles/style";
import { readFile, mkdir, writeFile, readdir } from "node:fs/promises";
import { resolve } from "node:path";

const directory = "custom_components/vegvesen/frontend";
const styles = {};
for (const theme of ["muted", "muted-dark"]) {
  const style = osm({ theme, projection: "mercator" });
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
  styles[theme] = style;
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
  plugins: [
    {
      name: "basemaps",
      setup(build) {
        build.onResolve({ filter: /^generated-styles$/ }, () => ({
          path: "styles",
          namespace: "generated",
        }));
        build.onLoad({ filter: /.*/, namespace: "generated" }, () => ({
          contents: `export default ${JSON.stringify(styles)}`,
        }));
      },
    },
  ],
});
const licenses = [
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
  ...[...result.outputFiles, ...worker.outputFiles].map((file) => [
    file.path,
    file.contents,
  ]),
  [resolve(directory, "LICENSES.md"), Buffer.from(notice.trimEnd() + "\n")],
];
if (!process.argv.includes("--check"))
  await mkdir(directory, { recursive: true });
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
