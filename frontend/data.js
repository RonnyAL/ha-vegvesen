export const COLORS = {
  NoNewPrecipitation: "#009e73",
  WetRoadSurface: "#56b4e9",
  IceOrFrost: "#e69f00",
  SnowCover: "#cc79a7",
  DriftingSnow: "#d55e00",
  ErrorOrNoData: "#777777",
};
export const UNKNOWN_COLOR = "#777777";
export const ROUTE_COLOR = "#174ea6";
export const color = (code) =>
  Object.hasOwn(COLORS, code) ? COLORS[code] : UNKNOWN_COLOR;
export const sourceLabel = (labels, code, kind = "condition") =>
  code == null
    ? labels.missing
    : (
          kind === "slip"
            ? ["low", "medium", "high"].includes(code)
            : Object.hasOwn(COLORS, code)
        )
      ? (labels[code] ?? String(code))
      : String(code);

export function lines(geometry) {
  return geometry?.type === "LineString"
    ? [geometry.coordinates]
    : (geometry?.coordinates ?? []);
}

export function displayGeometry(
  geometry,
  anchor = lines(geometry)[0]?.[0]?.[0],
) {
  if (!geometry) return null;
  const coordinates = lines(geometry).map((line) =>
    line.map(([lng, lat]) => [
      anchor + ((lng - anchor + 540) % 360) - 180,
      lat,
    ]),
  );
  return { type: "MultiLineString", coordinates };
}

export function bounds(geometry) {
  const extent = [
    [Infinity, Infinity],
    [-Infinity, -Infinity],
  ];
  for (const line of lines(displayGeometry(geometry)))
    for (const point of line) {
      for (let axis = 0; axis < 2; axis++) {
        extent[0][axis] = Math.min(extent[0][axis], point[axis]);
        extent[1][axis] = Math.max(extent[1][axis], point[axis]);
      }
    }
  return Number.isFinite(extent[0][0]) ? extent : undefined;
}

export function validateConfig(config) {
  if (!config?.entity?.startsWith("image."))
    throw Error("Select a Statens vegvesen route map image entity");
  if (
    config.height !== undefined &&
    (!Number.isFinite(config.height) ||
      config.height < 240 ||
      config.height > 1000)
  )
    throw Error("Height must be between 240 and 1000 pixels");
  if (config.map_style_url && !/^https?:\/\//.test(config.map_style_url))
    throw Error("map_style_url must be an HTTP(S) MapLibre style URL");
  return { ...config };
}

// HA calls a card's hass setter for all state changes. Fetch just this route's
// cached snapshot when its image changes or the connection recovers.
export class RouteData {
  constructor(onData, onError, onReset) {
    Object.assign(this, { onData, onError, onReset });
    this.generation = 0;
  }
  stop() {
    this.generation++;
    this.key = undefined;
  }
  async update(hass, entity) {
    const state = hass.states[entity];
    const key = `${entity}:${hass.connected}:${state?.last_updated}`;
    if (key === this.key) return;
    this.key = key;
    const generation = ++this.generation;
    if (
      !hass.connected ||
      !state ||
      ["unknown", "unavailable"].includes(state.state)
    ) {
      this.onReset();
      this.onError(!hass.connected ? "disconnected" : "unavailable");
      return;
    }
    try {
      const data = await hass.callWS({
        type: "vegvesen/route_map",
        entity_id: entity,
      });
      if (generation === this.generation) this.onData(data);
    } catch (error) {
      if (generation !== this.generation) return;
      this.onReset();
      this.onError(
        error.code === "unknown_command" ? "upgrade" : "unavailable",
      );
    }
  }
}
