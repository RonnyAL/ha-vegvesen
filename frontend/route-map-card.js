import * as maplibregl from "maplibre-gl";
import mapCSS from "maplibre-gl/dist/maplibre-gl.css";
import cardCSS from "./route-map-card.css";
import {
  bounds,
  category,
  highlighted,
  selectedBounds,
  selectedSegment,
  color,
  lines,
  ROUTE_COLOR,
  RouteData,
  displayGeometry,
  sourceLabel,
  validateConfig,
} from "./data.js";
import { labels, language } from "./labels.js";
import { darkMode, stubConfig } from "./config.js";
import { SourceOverlay } from "./source-overlay.js";
import "./editor.js";

maplibregl.setWorkerUrl(
  new URL("./maplibre-gl-worker.js", import.meta.url).href,
);

// All source/provider text is assigned through textContent, never HTML.
const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  if (tag === "button") element.type = "button";
  return element;
};
const icon = (name) => {
  const element = node("ha-icon");
  element.setAttribute("icon", name);
  element.setAttribute("aria-hidden", "true");
  return element;
};
const collection = (features) => ({ type: "FeatureCollection", features });
// Reserve the left control column when fitting the route.
const fitPadding = { top: 40, bottom: 40, left: 56, right: 40 };

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
    const card = (this._card = node("ha-card"));
    this._header = node("header");
    this._title = node("h2");
    this._time = node("div", "", "time");
    this._header.append(this._title);
    this._fit = node("button");
    this._fit.append(icon("mdi:image-filter-center-focus"));
    this._fit.onclick = () => this._fitRoute();
    this._mode = "condition";
    this._quality = node("div", "", "quality");
    this._qualityDetails = node("details", undefined, "data-quality");
    this._qualitySummary = node("summary");
    this._qualityDetails.append(this._qualitySummary, this._quality);
    this._modes = node("div", "", "modes");
    this._modes.setAttribute("role", "group");
    this._legendToggle = node("button");
    this._legendToggle.append(icon("mdi:layers-triple-outline"));
    this._legendToggle.setAttribute("aria-controls", "route-legend");
    this._legendToggle.onclick = () => {
      this._legendOpen = !this._legendOpen;
      if (this._legendOpen) {
        this._segmentId = undefined;
        this._cameras.close();
      }
      this._renderText();
      this._draw();
    };
    this._status = node("div", "", "status");
    this._status.setAttribute("role", "status");
    this._container = node("div", "", "map");
    this._basemap = node("div", "", "basemap");
    this._inspector = node("section", undefined, "inspector");
    this._inspector.hidden = true;
    this._inspector.setAttribute("aria-live", "polite");
    const inspectorHeading = node("div", undefined, "panel-heading");
    this._segmentTitle = node("h3");
    this._closeSegment = node("button", undefined, "panel-close");
    this._closeSegment.append(icon("mdi:close"));
    this._closeSegment.onclick = () => {
      this._segmentId = undefined;
      this._draw();
      this._renderInspector();
      this._map?.getCanvas().focus({ preventScroll: true });
    };
    inspectorHeading.append(this._segmentTitle, this._closeSegment);
    this._segmentValues = node("dl");
    this._segmentSource = node("div", undefined, "segment-id");
    this._inspector.append(
      inspectorHeading,
      this._segmentValues,
      this._segmentSource,
    );
    this._legendBody = node("div", "", "legend-body");
    this._legendHeading = node("div", undefined, "panel-heading");
    this._legendTitle = node("h3");
    this._closeLegend = node("button", undefined, "panel-close");
    this._closeLegend.append(icon("mdi:close"));
    this._closeLegend.onclick = () => {
      this._legendOpen = false;
      this._renderText();
      this._legendToggle.focus({ preventScroll: true });
    };
    this._legendHeading.append(this._legendTitle, this._closeLegend);
    this._summary = node("div", "", "legend-title");
    this._legend = node("div", "", "legend");
    this._legendBody.append(
      this._modes,
      this._summary,
      this._legend,
      this._qualityDetails,
    );
    this._information = node("div", undefined, "information");
    this._information.id = "route-legend";
    this._information.append(this._legendHeading, this._time, this._legendBody);
    this._frame = node("div", undefined, "map-frame");
    this._frame.append(
      this._container,
      this._inspector,
      this._information,
      this._status,
      this._basemap,
    );
    this._cameras = new SourceOverlay(
      this._frame,
      () => {
        this._segmentId = undefined;
        this._legendOpen = false;
        this._renderText();
        this._draw();
      },
      () => {
        if (!this._map && !this._webglFailed && this._routeGeometry)
          this._createMap();
        this._draw();
        this._renderText();
      },
    );
    card.append(this._header, this._frame);
    this.shadowRoot.append(css, card);
    this._data = new RouteData(
      (data) => {
        if (
          this._selection &&
          !data.segments.some((feature) =>
            highlighted(feature, this._selection),
          )
        )
          this._selection = undefined;
        this._snapshot = data;
        if (!selectedSegment(data, this._segmentId, this._selection))
          this._segmentId = undefined;
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
        this._segmentId = undefined;
        this._renderInspector();
        this._draw();
      },
    );
  }

  setConfig(config) {
    const next = validateConfig(config);
    const changed =
      this._config?.device_id !== next.device_id ||
      this._config?.entity !== next.entity;
    if (!this._config || this._config.default_mode !== next.default_mode) {
      this._mode = next.default_mode ?? "condition";
      this._selection = undefined;
    }
    if (!this._config || this._config.legend_expanded !== next.legend_expanded)
      this._legendOpen = next.legend_expanded ?? false;
    this._config = next;
    this.style.setProperty("--map-height", `${next.height ?? 400}px`);
    if (changed) {
      this._cameras.stop();
      this._data.stop();
      this._snapshot = undefined;
      this._selection = undefined;
      this._segmentId = undefined;
      this._destroyMap();
    }
    this._renderText();
    this._update();
    this._draw();
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
    this._cameras.stop();
    this._destroyMap();
  }

  _update() {
    if (!this.isConnected || !this._config || !this._hass) return;
    const previousLanguage = this._lang;
    this._lang = language(this._hass);
    this._labels = labels[this._lang];
    const dark = darkMode(this._config, this._hass);
    if (this._map && previousLanguage !== this._lang) this._destroyMap();
    this._dark = dark;
    this._card.dataset.theme = dark ? "dark" : "light";
    this._card.dataset.mode = this._config.theme_mode ?? "auto";
    const style = this._styleUrl();
    if (this._map && this._styleKey !== style) {
      this._styleKey = style;
      this._ready = false;
      this._fallback = false;
      this._basemap.textContent = "";
      // MapLibre's public style lifecycle retains the camera and controls.
      // Our source layers are restored on style.load from the latest snapshot.
      this._map.setStyle(style);
    }
    const timeZone = this._hass.config?.time_zone;
    if (previousLanguage !== this._lang || this._timeZone !== timeZone)
      this._renderText();
    this._timeZone = timeZone;
    if (!this._map && !this._webglFailed && this._routeGeometry)
      this._createMap();
    this._data.update(this._hass, this._config);
    this._updateCameras();
  }

  _updateCameras() {
    const l = this._labels ?? labels.en;
    this._cameras.update(this._hass, this._config, l, this._map);
  }

  get _routeGeometry() {
    return this._snapshot?.geometry ?? this._cameras.snapshot?.geometry;
  }

  _styleUrl() {
    if (this._config.map_style_url) return this._config.map_style_url;
    const url = new URL(
      `./styles/${this._config.map_style ?? "default"}-${this._dark ? "dark" : "light"}.json`,
      import.meta.url,
    );
    url.search = new URL(import.meta.url).search;
    return url.href;
  }

  _createMap() {
    if (!this._routeGeometry || !this.isConnected) return;
    try {
      const map = (this._map = new maplibregl.Map({
        container: this._container,
        style: (this._styleKey = this._styleUrl()),
        bounds: bounds(this._routeGeometry),
        fitBoundsOptions: { padding: fitPadding, maxZoom: 15 },
        maxZoom: 20,
        // Match HA's vector map: responsive attribution, open initially.
        attributionControl: {},
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
          "FullscreenControl.Enter": this._labels.expand,
          "FullscreenControl.Exit": this._labels.collapse,
          "AttributionControl.ToggleAttribution": this._labels.attribution,
        },
      }));
      map.touchZoomRotate.disableRotation();
      map.addControl(
        new maplibregl.NavigationControl({ showCompass: false }),
        "top-left",
      );
      map.addControl(
        {
          onAdd: () => {
            const group = node(
              "div",
              undefined,
              "maplibregl-ctrl maplibregl-ctrl-group",
            );
            group.append(this._fit);
            return group;
          },
          onRemove: () => this._fit.parentNode?.remove(),
        },
        "top-left",
      );
      map.addControl(
        new maplibregl.FullscreenControl({ container: this._card }),
        "top-left",
      );
      map.addControl(
        {
          onAdd: () => {
            const group = node(
              "div",
              undefined,
              "maplibregl-ctrl maplibregl-ctrl-group",
            );
            group.append(this._legendToggle);
            return group;
          },
          onRemove: () => this._legendToggle.parentNode?.remove(),
        },
        "top-left",
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
        // A missing local or custom style still leaves a usable vector route.
        if (!this._ready && !this._fallback) {
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
    this._cameras.removeMarkers();
    this._markers?.forEach((marker) => marker.remove());
    this._markers = [];
    this._map?.remove();
    // Release expansion when this card detaches or rebuilds its map. MapLibre
    // owns the controls; browser fullscreen and its CSS fallback belong to
    // this card's container only.
    if (this.shadowRoot.fullscreenElement === this._card)
      document.exitFullscreen?.().catch(() => {});
    this._card.classList.remove("maplibregl-pseudo-fullscreen");
    this._map = undefined;
    this._ready = false;
    this._fitted = false;
    this._fallback = false;
    this._basemap.textContent = "";
  }

  _draw() {
    this._updateCameras();
    const map = this._map;
    if (!map || !this._ready) return;
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
      for (const [id, color, padding] of [
        ["segment-outline", "#222222", 6],
        ["segment-highlight", "#ffffff", 4],
      ])
        map.addLayer({
          id,
          type: "line",
          source: "forecasts",
          layout: { "line-cap": "round", "line-join": "round" },
          paint: { "line-color": color, "line-width": lineWidth(padding) },
          filter: ["==", ["get", "_id"], null],
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
    const geometry = this._routeGeometry;
    for (const id of ["segment-outline", "segment-highlight"])
      map.setFilter(id, ["==", ["get", "_id"], this._segmentId ?? null]);
    map.setPaintProperty("route", "line-opacity", this._selection ? 0.35 : 1);
    map.getSource("route").setData(
      collection(
        geometry
          ? [
              {
                type: "Feature",
                geometry: displayGeometry(geometry),
                properties: {},
              },
            ]
          : [],
      ),
    );
    map.getSource("forecasts").setData(
      collection(
        data?.segments
          .filter(
            (feature) =>
              feature.geometry && highlighted(feature, this._selection),
          )
          .map((feature) => ({
            ...feature,
            geometry: displayGeometry(
              feature.geometry,
              lines(data.geometry)[0][0][0],
            ),
            properties: {
              _id: feature.id,
              _color: color(category(feature, this._mode), this._mode),
            },
          })) ?? [],
      ),
    );
    if (!geometry) return;
    const routeLines = lines(displayGeometry(geometry));
    const points = [routeLines[0]?.[0], routeLines.at(-1)?.at(-1)];
    points.forEach((point, index) => {
      if (!point) return;
      const element = node("div", index === 0 ? "A" : "B", "marker");
      element.title = index === 0 ? this._labels.start : this._labels.end;
      this._markers.push(
        new maplibregl.Marker({ element }).setLngLat(point).addTo(map),
      );
    });
    const geometryKey = JSON.stringify(geometry);
    if (!this._fitted || this._geometryKey !== geometryKey) {
      this._fitted = true;
      this._geometryKey = geometryKey;
      this._fitRoute();
    }
  }

  _fitRoute() {
    this._cameras.close();
    this._selection = undefined;
    this._segmentId = undefined;
    this._renderText();
    if (this._ready && this._fitted) this._draw();
    const extent = this._routeGeometry && bounds(this._routeGeometry);
    if (extent)
      this._map?.fitBounds(extent, {
        padding: fitPadding,
        maxZoom: 15,
        duration: 0,
      });
  }

  _select(mode, code) {
    const repeated =
      this._selection?.mode === mode && this._selection.code === code;
    this._mode = mode;
    this._selection = repeated ? undefined : { mode, code };
    this._segmentId = undefined;
    this._renderText();
    this._draw();
    const extent =
      this._selection &&
      selectedBounds(this._snapshot.segments, this._selection);
    if (extent)
      this._map?.fitBounds(extent, {
        padding: fitPadding,
        maxZoom: 15,
        duration: 0,
      });
    else if (repeated) this._fitRoute();
  }

  _setMode(mode) {
    if (mode === this._mode) return;
    this._mode = mode;
    // Category filters belong to one layer. Clear them without changing the
    // map camera so users can compare both forecasts in the same area.
    this._selection = undefined;
    this._renderText();
    this._draw();
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
    this._cameras.close();
    this._segmentId = feature.id;
    this._legendOpen = false;
    this._draw();
    this._renderText();
  }

  _renderInspector() {
    const feature = selectedSegment(
      this._snapshot,
      this._segmentId,
      this._selection,
    );
    this._inspector.hidden = !feature;
    this._information.hidden =
      !this._snapshot || !!feature || (!this._legendOpen && !this._webglFailed);
    if (!feature) {
      this._segmentValues.replaceChildren();
      this._segmentTitle.textContent = "";
      this._segmentSource.textContent = "";
      return;
    }
    const props = feature.properties;
    const l = this._labels ?? labels.en;
    this._inspector.setAttribute("aria-label", l.segment);
    this._segmentTitle.textContent = sourceLabel(l, props.ROAD_CONDITION);
    this._closeSegment.title = l.close_segment;
    this._closeSegment.setAttribute("aria-label", l.close_segment);
    this._segmentValues.replaceChildren();
    for (const [label, value] of [
      [l.slip, sourceLabel(l, props.SLIP_RISK, "slip")],
      [
        l.temperature,
        props.ROAD_TEMPERATURE == null
          ? l.missing
          : `${props.ROAD_TEMPERATURE} °C`,
      ],
      [l.forecast, this._formatTime(this._snapshot.forecast_time)],
    ]) {
      const field = node("div");
      field.append(node("dt", label), node("dd", value));
      this._segmentValues.append(field);
    }
    this._segmentSource.textContent = `${l.segment} ${props.ROAD_SEGMENT_ID ?? feature.id}`;
  }

  _renderText() {
    const focusedKey = this.shadowRoot.activeElement?.dataset?.focusKey;
    const l = this._labels ?? labels.en;
    this._title.textContent = this._config?.title ?? "";
    this._header.hidden = !this._title.textContent.trim();
    this._fit.title = l.fit;
    this._fit.setAttribute("aria-label", l.fit);
    this._fit.disabled = !this._routeGeometry || this._webglFailed;
    this._summary.textContent = l.legend;
    this._legendTitle.textContent = l.forecast_layer;
    this._modes.setAttribute("aria-label", l.forecast_layer);
    this._closeLegend.hidden = !!this._webglFailed;
    this._closeLegend.title = l.close_layers;
    this._closeLegend.setAttribute("aria-label", l.close_layers);
    this._legendToggle.title = l.layers;
    this._legendToggle.setAttribute("aria-label", l.layers);
    this._legendToggle.setAttribute(
      "aria-expanded",
      String(!!this._legendOpen),
    );
    this._qualitySummary.textContent = l.data_gaps;
    this._qualityDetails.hidden = true;
    this._quality.textContent = "";
    this._modes.replaceChildren();
    this._status.replaceChildren();
    if (this._webglFailed) this._status.textContent = l.webgl;
    else if (this._error) {
      this._status.append(node("span", l[this._error]));
      if (this._error !== "invalid_route") {
        const retry = node("button", l.retry);
        retry.onclick = () => {
          this._data.stop();
          this._cameras.stop();
          this._update();
        };
        this._status.append(retry);
      }
    } else if (!this._snapshot) this._status.textContent = l.loading;
    for (const notice of this._cameras.notices)
      this._status.append(node("span", notice));
    this._time.textContent = this._snapshot
      ? this._formatTime(this._snapshot.forecast_time)
      : "";
    this._time.title = `${l.forecast}: ${this._time.textContent}`;
    this._time.setAttribute("aria-label", this._time.title);
    this._legend.replaceChildren();
    this._renderInspector();
    if (!this._snapshot) return;
    const summary = this._snapshot.summary;
    const warnings = [];
    for (const [key, label] of [
      ["slip_risk", l.slip],
      ["road_condition", l.condition],
    ]) {
      const value = summary[key];
      if (value.missing_segments)
        warnings.push(`${label} — ${l.missing}: ${value.missing_segments}`);
      if (value.unrecognized_segments)
        warnings.push(
          `${label} — ${l.unrecognized}: ${value.unrecognized_segments}`,
        );
    }
    this._quality.replaceChildren(...warnings.map((text) => node("div", text)));
    this._qualityDetails.hidden = !warnings.length;
    for (const mode of ["condition", "slip"]) {
      const button = node("button", l[mode]);
      button.dataset.focusKey = mode;
      button.setAttribute("aria-pressed", String(this._mode === mode));
      button.onclick = () => this._setMode(mode);
      this._modes.append(button);
    }
    const values =
      summary[this._mode === "slip" ? "slip_risk" : "road_condition"];
    const categories = Object.entries(values.source_categories);
    const absent =
      values.missing_segments - (values.source_categories.ErrorOrNoData ?? 0);
    if (absent) categories.push([null, absent]);
    for (const [code, count] of categories) {
      const item = node("button");
      item.dataset.focusKey = JSON.stringify([this._mode, code]);
      const swatch = node("i", "", "swatch");
      swatch.style.background = color(code, this._mode);
      swatch.setAttribute("aria-hidden", "true");
      item.append(
        swatch,
        node("span", sourceLabel(l, code, this._mode), "category-name"),
        node("span", String(count), "category-count"),
      );
      item.setAttribute(
        "aria-label",
        `${sourceLabel(l, code, this._mode)}: ${count}`,
      );
      item.setAttribute(
        "aria-pressed",
        String(
          this._selection?.mode === this._mode && this._selection.code === code,
        ),
      );
      item.disabled =
        this._webglFailed ||
        !selectedBounds(this._snapshot.segments, { mode: this._mode, code });
      item.onclick = () => this._select(this._mode, code);
      this._legend.append(item);
    }
    if (!categories.length) this._legend.append(node("span", l.empty));
    if (focusedKey) {
      const button = [
        ...this.shadowRoot.querySelectorAll("button[data-focus-key]"),
      ].find((element) => element.dataset.focusKey === focusedKey);
      button?.focus({ preventScroll: true });
    }
  }

  getCardSize() {
    return Math.ceil(
      (this.getBoundingClientRect().height ||
        (this._config?.height ?? 400) + (this._config?.title ? 56 : 0)) / 50,
    );
  }
  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }
  static getStubConfig(hass) {
    return stubConfig(hass);
  }
  static getConfigElement() {
    return document.createElement("vegvesen-route-map-editor");
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
    documentationURL: "https://github.com/RonnyAL/ha-vegvesen#route-maps",
  });
