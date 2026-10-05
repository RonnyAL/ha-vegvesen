import { MAP_STYLES, THEME_MODES } from "./config.js";

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
export const selectedSegment = (snapshot, id, selection) =>
  id === undefined
    ? undefined
    : snapshot?.segments.find(
        (feature) =>
          feature.id === id &&
          feature.geometry &&
          highlighted(feature, selection),
      );
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
  if (
    !config ||
    (config.device_id !== undefined && typeof config.device_id !== "string") ||
    (!config.device_id &&
      config.entity &&
      !config.entity.startsWith?.("sensor."))
  )
    throw Error("Select a Statens vegvesen route");
  if (config.title !== undefined && typeof config.title !== "string")
    throw Error("Title must be text");
  if (config.map_style !== undefined && !MAP_STYLES.includes(config.map_style))
    throw Error("Select a supported map style");
  if (
    config.theme_mode !== undefined &&
    !THEME_MODES.includes(config.theme_mode)
  )
    throw Error("Theme mode must be auto, light or dark");
  if (
    config.default_mode !== undefined &&
    !["condition", "slip"].includes(config.default_mode)
  )
    throw Error("Initial layer must be road condition or slipperiness");
  if (
    config.legend_expanded !== undefined &&
    typeof config.legend_expanded !== "boolean"
  )
    throw Error("Expand legend must be true or false");
  if (
    config.height !== undefined &&
    (!Number.isFinite(config.height) ||
      config.height < 240 ||
      config.height > 1000)
  )
    throw Error("Height must be between 240 and 1000 pixels");
  if (config.map_style_url && !/^https?:\/\//.test(config.map_style_url))
    throw Error("map_style_url must be an HTTP(S) MapLibre style URL");
  if (
    config.show_cameras !== undefined &&
    typeof config.show_cameras !== "boolean"
  )
    throw Error("Show cameras must be true or false");
  if (
    config.camera_distance_m !== undefined &&
    (!Number.isInteger(config.camera_distance_m) ||
      config.camera_distance_m < 1 ||
      config.camera_distance_m > 2000)
  )
    throw Error("Camera distance must be between 1 and 2000 meters");
  const result = { ...config };
  if (result.device_id) delete result.entity;
  return result;
}

export const routeTarget = (config) =>
  config.device_id
    ? { device_id: config.device_id }
    : config.entity
      ? { entity_id: config.entity }
      : undefined;

// Subscribe to cached snapshot changes, independently of sensor states.
export class RouteData {
  constructor(onData, onError, onReset) {
    Object.assign(this, { onData, onError, onReset });
    this.generation = 0;
  }
  stop() {
    this.generation++;
    this.connection = undefined;
    this.targetKey = undefined;
    if (this.unsubscribe) {
      // The socket may already have closed. Its server subscriptions are gone.
      Promise.resolve(this.unsubscribe()).catch(() => {});
      this.unsubscribe = undefined;
    }
  }
  async update(hass, config) {
    if (!hass.connected) {
      if (this.disconnected) return;
      this.stop();
      this.disconnected = true;
      this.onReset();
      this.onError("disconnected");
      return;
    }
    this.disconnected = false;
    const target = routeTarget(config);
    const key = JSON.stringify(target ?? null);
    if (this.connection === hass.connection && this.targetKey === key) return;
    this.stop();
    this.connection = hass.connection;
    this.targetKey = key;
    const generation = this.generation;
    this.onReset();
    if (!target) {
      this.onError("invalid_route");
      return;
    }
    try {
      const unsubscribe = await hass.connection.subscribeMessage(
        (event) => {
          if (generation !== this.generation) return;
          if (event.error) {
            this.onReset();
            this.onError(event.error);
          } else this.onData(event.data);
        },
        { type: "vegvesen/subscribe_route_map", ...target },
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
