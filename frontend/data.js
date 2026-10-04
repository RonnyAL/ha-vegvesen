export const COLORS = {
  NoNewPrecipitation: "#009e73",
  WetRoadSurface: "#56b4e9",
  IceOrFrost: "#e69f00",
  SnowCover: "#cc79a7",
  DriftingSnow: "#d55e00",
  ErrorOrNoData: "#777777",
};
export const UNKNOWN_COLOR = "#777777";
export const SLIP_COLORS = {
  low: "#009e73",
  medium: "#e69f00",
  high: "#d55e00",
};
export const ROUTE_COLOR = "#174ea6";
export const color = (code, mode = "condition") => {
  const colors = mode === "slip" ? SLIP_COLORS : COLORS;
  return Object.hasOwn(colors, code) ? colors[code] : UNKNOWN_COLOR;
};
export const category = (feature, mode) =>
  feature.properties[mode === "slip" ? "SLIP_RISK" : "ROAD_CONDITION"] ?? null;
export const highlighted = (feature, selection) =>
  !selection || category(feature, selection.mode) === selection.code;
export const selectedBounds = (segments, selection) => {
  const selected = segments.filter(
    (feature) => feature.geometry && highlighted(feature, selection),
  );
  return selected.length
    ? bounds({
        type: "MultiLineString",
        coordinates: selected.flatMap((feature) => lines(feature.geometry)),
      })
    : undefined;
};
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
  if (!config?.entity?.startsWith("sensor."))
    throw Error("Select a Statens vegvesen route forecast sensor");
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

// Subscribe to cached snapshot changes, independently of the anchor sensor state.
export class RouteData {
  constructor(onData, onError, onReset) {
    Object.assign(this, { onData, onError, onReset });
    this.generation = 0;
  }
  stop() {
    this.generation++;
    this.connection = undefined;
    this.entity = undefined;
    if (this.unsubscribe) {
      // The socket may already have closed. Its server subscriptions are gone.
      Promise.resolve(this.unsubscribe()).catch(() => {});
      this.unsubscribe = undefined;
    }
  }
  async update(hass, entity) {
    if (!hass.connected) {
      if (this.disconnected) return;
      this.stop();
      this.disconnected = true;
      this.onReset();
      this.onError("disconnected");
      return;
    }
    this.disconnected = false;
    if (this.connection === hass.connection && this.entity === entity) return;
    this.stop();
    this.connection = hass.connection;
    this.entity = entity;
    const generation = this.generation;
    this.onReset();
    try {
      const unsubscribe = await hass.connection.subscribeMessage(
        (event) => {
          if (generation !== this.generation) return;
          if (event.error) {
            this.onReset();
            this.onError(event.error);
          } else this.onData(event.data);
        },
        { type: "vegvesen/subscribe_route_map", entity_id: entity },
      );
      if (generation !== this.generation) await unsubscribe();
      else this.unsubscribe = unsubscribe;
    } catch (error) {
      if (generation !== this.generation) return;
      this.onReset();
      this.onError(
        error.code === "unknown_command"
          ? "upgrade"
          : error.code === "invalid_route"
            ? "invalid_route"
            : error.code === "unauthorized"
              ? "unauthorized"
              : "unavailable",
      );
    }
  }
}
