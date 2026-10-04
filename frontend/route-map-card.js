import * as maplibregl from "maplibre-gl";
import mapCSS from "maplibre-gl/dist/maplibre-gl.css";
import cardCSS from "./route-map-card.css";
import styles from "generated-styles";
import {
  bounds,
  color,
  lines,
  ROUTE_COLOR,
  RouteData,
  displayGeometry,
  sourceLabel,
  validateConfig,
} from "./data.js";
import { labels, language } from "./labels.js";

maplibregl.setWorkerUrl(
  new URL("./maplibre-gl-worker.js", import.meta.url).href,
);

// All source/provider text is assigned through textContent, never HTML.
const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
};
const collection = (features) => ({ type: "FeatureCollection", features });

// Follow the default basemap's main-road scale, retaining a visible overview.
// Forecast and OSM features have no shared road ID/width, so this is a visual
// approximation, not a physical road-width measurement.
const lineWidth = (padding = 0, minimum = 0) => [
  "interpolate",
  ["linear"],
  ["zoom"],
  ...[
    [6, 1.25],
    [10, 2.5],
    [14, 5],
    [16, 10],
    [18, 34],
    [19, 70],
    [20, 140],
  ].flatMap(([zoom, width]) => [zoom, Math.max(minimum, width + padding)]),
];

export class VegvesenRouteMap extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    const css = node("style", mapCSS + cardCSS);
    const card = node("ha-card");
    const header = node("header");
    this._title = node("h2");
    this._fit = node("button");
    this._fit.onclick = () => this._fitRoute();
    header.append(this._title, this._fit);
    this._status = node("div", "", "status");
    this._status.setAttribute("role", "status");
    this._container = node("div", "", "map");
    this._basemap = node("div", "", "basemap");
    this._time = node("div", "", "time");
    this._details = node("details");
    this._summary = node("summary");
    this._legend = node("div", "", "legend");
    this._details.append(this._summary, this._legend);
    card.append(
      header,
      this._status,
      this._container,
      this._basemap,
      this._time,
      this._details,
    );
    this.shadowRoot.append(css, card);
    this._data = new RouteData(
      (data) => {
        this._snapshot = data;
        this._error = undefined;
        this._renderText();
        if (!this._map && !this._webglFailed) this._createMap();
        this._draw();
      },
      (error) => {
        this._error = error;
        this._renderText();
      },
      () => {
        this._snapshot = undefined;
        this._popup?.remove();
        this._draw();
      },
    );
  }

  setConfig(config) {
    const next = validateConfig(config);
    const changed =
      this._config?.entity !== next.entity ||
      this._config?.map_style_url !== next.map_style_url;
    this._config = next;
    this.style.setProperty("--map-height", `${next.height ?? 400}px`);
    if (changed) {
      this._data.stop();
      this._snapshot = undefined;
      this._destroyMap();
    }
    this._update();
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  connectedCallback() {
    this._update();
  }
  disconnectedCallback() {
    this._data.stop();
    this._destroyMap();
  }

  _update() {
    if (!this.isConnected || !this._config || !this._hass) return;
    const previousLanguage = this._lang;
    this._lang = language(this._hass);
    this._labels = labels[this._lang];
    const dark = !!this._hass.themes?.darkMode;
    if (
      this._map &&
      (previousLanguage !== this._lang ||
        (this._dark !== dark && !this._config.map_style_url))
    )
      this._destroyMap();
    this._dark = dark;
    this._renderText();
    if (!this._map && !this._webglFailed && this._snapshot) this._createMap();
    this._data.update(this._hass, this._config.entity);
  }

  _createMap() {
    if (!this._snapshot || !this.isConnected) return;
    try {
      const map = (this._map = new maplibregl.Map({
        container: this._container,
        style:
          this._config.map_style_url ??
          structuredClone(styles[this._dark ? "muted-dark" : "muted"]),
        bounds: bounds(this._snapshot.geometry),
        fitBoundsOptions: { padding: 40, maxZoom: 15 },
        maxZoom: 20,
        attributionControl: false,
        // Send no HA credentials to map providers. Let the browser cache tiles.
        transformRequest: (url) => ({
          url,
          credentials: "omit",
          referrerPolicy: "strict-origin-when-cross-origin",
        }),
        dragRotate: false,
        pitchWithRotate: false,
        renderWorldCopies: false,
        locale: {
          "NavigationControl.ZoomIn":
            this._lang === "nb" ? "Zoom inn" : "Zoom in",
          "NavigationControl.ZoomOut":
            this._lang === "nb" ? "Zoom ut" : "Zoom out",
        },
      }));
      map.touchZoomRotate.disableRotation();
      map.addControl(
        new maplibregl.NavigationControl({ showCompass: false }),
        "top-right",
      );
      map.addControl(
        new maplibregl.AttributionControl({ compact: false }),
        "bottom-right",
      );
      map.on("style.load", () => {
        if (this._map !== map) return;
        this._ready = true;
        this._draw();
      });
      map.on("error", () => {
        const retry = node("button", this._labels.retry);
        retry.onclick = () => {
          this._destroyMap();
          this._createMap();
        };
        this._basemap.replaceChildren(
          node("span", this._labels.basemap),
          retry,
        );
        // Invalid/unreachable optional styles still leave a usable vector route.
        if (!this._ready && this._config.map_style_url && !this._fallback) {
          this._fallback = true;
          map.setStyle({ version: 8, sources: {}, layers: [] });
        }
      });
      map.on("click", "forecasts-hit", (event) => this._showSegment(event));
      map.on("mouseenter", "forecasts-hit", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "forecasts-hit", () => {
        map.getCanvas().style.cursor = "";
      });
      this._observer = new ResizeObserver(() => map.resize());
      this._observer.observe(this._container);
    } catch {
      this._webglFailed = true;
      this._destroyMap();
      this._renderText();
    }
  }

  _destroyMap() {
    this._observer?.disconnect();
    this._popup?.remove();
    this._markers?.forEach((marker) => marker.remove());
    this._markers = [];
    this._map?.remove();
    this._map = undefined;
    this._ready = false;
    this._fitted = false;
    this._fallback = false;
    this._basemap.textContent = "";
  }

  _draw() {
    const map = this._map;
    if (!map || !this._ready) return;
    this._popup?.remove();
    this._markers?.forEach((marker) => marker.remove());
    this._markers = [];
    if (!map.getSource("route")) {
      map.addSource("route", { type: "geojson", data: collection([]) });
      map.addLayer({
        id: "route-border",
        type: "line",
        source: "route",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#ffffff", "line-width": lineWidth(2) },
      });
      map.addLayer({
        id: "route",
        type: "line",
        source: "route",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": ROUTE_COLOR, "line-width": lineWidth(1) },
      });
      map.addSource("forecasts", {
        type: "geojson",
        data: collection([]),
        promoteId: "_id",
      });
      map.addLayer({
        id: "forecasts",
        type: "line",
        source: "forecasts",
        layout: { "line-join": "round" },
        paint: { "line-color": ["get", "_color"], "line-width": lineWidth() },
      });
      // Keep narrow overview lines easy to tap without drawing them wider.
      map.addLayer({
        id: "forecasts-hit",
        type: "line",
        source: "forecasts",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-opacity": 0, "line-width": lineWidth(0, 20) },
      });
    }
    const data = this._snapshot;
    map.getSource("route").setData(
      collection(
        data
          ? [
              {
                type: "Feature",
                geometry: displayGeometry(data.geometry),
                properties: {},
              },
            ]
          : [],
      ),
    );
    map.getSource("forecasts").setData(
      collection(
        data?.segments
          .filter((feature) => feature.geometry)
          .map((feature) => ({
            ...feature,
            geometry: displayGeometry(
              feature.geometry,
              lines(data.geometry)[0][0][0],
            ),
            properties: {
              _id: feature.id,
              _color: color(feature.properties.ROAD_CONDITION),
            },
          })) ?? [],
      ),
    );
    if (!data) return;
    const routeLines = lines(displayGeometry(data.geometry));
    const points = [routeLines[0]?.[0], routeLines.at(-1)?.at(-1)];
    points.forEach((point, index) => {
      if (!point) return;
      const element = node("div", index === 0 ? "A" : "B", "marker");
      element.title = index === 0 ? this._labels.start : this._labels.end;
      this._markers.push(
        new maplibregl.Marker({ element }).setLngLat(point).addTo(map),
      );
    });
    const geometryKey = JSON.stringify(data.geometry);
    if (!this._fitted || this._geometryKey !== geometryKey) {
      this._fitRoute();
      this._fitted = true;
      this._geometryKey = geometryKey;
    }
  }

  _fitRoute() {
    const extent = this._snapshot && bounds(this._snapshot.geometry);
    if (extent)
      this._map?.fitBounds(extent, { padding: 40, maxZoom: 15, duration: 0 });
  }

  _formatTime(value) {
    const date = new Date(value);
    return Number.isNaN(date.valueOf())
      ? value
      : new Intl.DateTimeFormat(this._lang, {
          dateStyle: "short",
          timeStyle: "short",
          timeZone: this._hass.config?.time_zone,
        }).format(date);
  }

  _showSegment(event) {
    // Prefer a visible stroke over another segment's overlapping tap target.
    const id =
      this._map.queryRenderedFeatures(event.point, { layers: ["forecasts"] })[0]
        ?.id ?? event.features?.[0]?.id;
    const feature = this._snapshot?.segments.find(
      (segment) => segment.id === id,
    );
    if (!feature) return;
    const props = feature.properties;
    const content = node("div", "", "popup");
    const l = this._labels;
    content.append(
      node("strong", `${l.segment} ${props.ROAD_SEGMENT_ID ?? feature.id}`),
    );
    for (const [label, value] of [
      [l.condition, sourceLabel(l, props.ROAD_CONDITION)],
      [
        l.temperature,
        props.ROAD_TEMPERATURE == null
          ? l.missing
          : `${props.ROAD_TEMPERATURE} °C`,
      ],
      [l.slip, sourceLabel(l, props.SLIP_RISK, "slip")],
      [l.forecast, this._formatTime(this._snapshot.forecast_time)],
    ])
      content.append(node("p", `${label}: ${value}`));
    this._popup?.remove();
    this._popup = new maplibregl.Popup({ maxWidth: "280px" })
      .setLngLat(event.lngLat)
      .setDOMContent(content)
      .addTo(this._map);
  }

  _renderText() {
    const l = this._labels ?? labels.en;
    this._title.textContent =
      this._config?.title ?? this._snapshot?.name ?? l.title;
    this._fit.textContent = l.fit;
    this._fit.disabled = !this._snapshot || this._webglFailed;
    this._summary.textContent = l.legend;
    this._status.replaceChildren();
    if (this._webglFailed) this._status.textContent = l.webgl;
    else if (this._error) {
      this._status.append(node("span", l[this._error]));
      const retry = node("button", l.retry);
      retry.onclick = () => {
        this._data.stop();
        this._update();
      };
      this._status.append(retry);
    } else if (!this._snapshot) this._status.textContent = l.loading;
    this._time.textContent = this._snapshot
      ? `${l.forecast}: ${this._formatTime(this._snapshot.forecast_time)}`
      : "";
    this._legend.replaceChildren();
    this._details.hidden = !this._snapshot;
    if (!this._snapshot) return;
    const codes = new Set(
      this._snapshot.segments.map(
        (segment) => segment.properties.ROAD_CONDITION,
      ),
    );
    for (const code of codes) {
      const item = node("span");
      const swatch = node("i", "", "swatch");
      swatch.style.background = color(code);
      item.append(swatch, document.createTextNode(sourceLabel(l, code)));
      this._legend.append(item);
    }
    if (!codes.size) this._legend.append(node("span", l.empty));
    const missing = this._snapshot.segments.filter(
      (segment) => !segment.geometry,
    ).length;
    if (missing)
      this._legend.append(node("span", `${l.no_geometry}: ${missing}`));
  }

  getCardSize() {
    return 7;
  }
  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }
  static getStubConfig(hass) {
    return {
      entity:
        Object.keys(hass.states).find(
          (id) =>
            id.startsWith("image.") &&
            hass.entities?.[id]?.platform === "vegvesen",
        ) ?? "",
    };
  }
  static getConfigForm() {
    return {
      schema: [
        {
          name: "entity",
          required: true,
          selector: {
            entity: { filter: [{ integration: "vegvesen", domain: "image" }] },
          },
        },
      ],
    };
  }
}

if (!customElements.get("vegvesen-route-map"))
  customElements.define("vegvesen-route-map", VegvesenRouteMap);
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "vegvesen-route-map"))
  window.customCards.push({
    type: "vegvesen-route-map",
    name: "Statens vegvesen route map",
    preview: true,
    description: "Interactive route and road-condition forecasts",
    documentationURL: "https://github.com/RonnyAL/ha-vegvesen#route-maps-beta",
  });
