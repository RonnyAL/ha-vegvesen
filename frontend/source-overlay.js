import { SourceMarkers, element, icon } from "./source-markers.js";
import { RouteData, routeTarget } from "./data.js";
import { sourceRequest, sourceItems, stationValues } from "./sources.js";

// Shared discovery supplies metadata. Only a selected camera requests an image.
export class SourceOverlay {
  constructor(frame, onOpen, onChange) {
    Object.assign(this, { onOpen, onChange });
    this.items = [];
    this.sources = new SourceMarkers(
      frame,
      (item, keyboard) => {
        this.onOpen();
        this.select(item);
        if (keyboard) this.closeButton.focus({ preventScroll: true });
      },
      () => {
        this.close(false);
        this.onOpen();
      },
    );
    this.data = new RouteData(
      (data) => {
        this.snapshot = data;
        this.error = undefined;
        this.draw();
        this.onChange();
      },
      (error) => {
        this.error = error;
        this.onChange();
      },
      () => {
        this.snapshot = this.error = undefined;
        this.close();
        this.draw();
        this.onChange();
      },
      sourceRequest,
    );
    this.panel = element("section", "camera-panel");
    this.panel.hidden = true;
    const heading = element("div", "panel-heading");
    this.title = element("h3");
    this.closeButton = element("button", "panel-close");
    this.closeButton.append(icon("mdi:close"));
    this.closeButton.onclick = (event) => {
      this.close(false);
      this.sources.release(event.detail === 0);
    };
    this.panel.onkeydown = (event) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        this.close(false);
        this.sources.release(true);
      }
    };
    heading.append(this.title, this.closeButton);
    this.image = element("img", "camera-image");
    this.image.hidden = true;
    this.values = element("dl", "source-values");
    this.message = element("div", "camera-message");
    this.message.setAttribute("role", "status");
    this.source = element("div", "camera-source");
    this.panel.append(
      heading,
      this.image,
      this.values,
      this.message,
      this.source,
    );
    frame.append(this.panel);
  }

  update(hass, config, labels, map) {
    Object.assign(this, { hass, config, labels, map });
    if (!hass || (!config?.show_cameras && !config?.show_weather)) {
      this.stop();
      return;
    }
    this.data.update(hass, config);
    this.draw();
  }

  draw() {
    this.items = sourceItems(this.snapshot);
    this.count = this.items.length;
    this.sources.update(this.items, this.map, this.labels);
    if (this.selected) {
      const current = this.items.find((item) => item.id === this.selected.id);
      if (!current) this.close();
      else {
        this.selected = current;
        this.render();
      }
    }
  }

  get notices() {
    if (!this.config?.show_cameras && !this.config?.show_weather) return [];
    if (this.error) return [this.labels[this.error]];
    const states = ["cameras", "weather"].filter(
      (kind) => this.config[`show_${kind}`],
    );
    const errors = states
      .filter((kind) => this.snapshot?.[kind]?.status === "unavailable")
      .map((kind) => this.labels[`${kind}_unavailable`]);
    if (
      states.some(
        (kind) =>
          !this.snapshot?.[kind] || this.snapshot[kind].status === "loading",
      )
    )
      errors.push(this.labels.sources_loading);
    return errors;
  }

  select(item) {
    this.close(false);
    this.selected = item;
    this.render();
    if (item.kind === "cameras") {
      this.loadImage();
      this.timer = setInterval(() => {
        if (document.visibilityState !== "hidden") this.loadImage();
      }, 60000);
    }
  }

  render() {
    if (!this.selected) return;
    const { kind, name, source } = this.selected;
    const l = this.labels;
    this.panel.hidden = false;
    this.panel.setAttribute(
      "aria-label",
      kind === "cameras" ? l.road_cameras : l.weather_stations,
    );
    this.title.textContent = name;
    this.closeButton.title = l.close_source;
    this.closeButton.setAttribute("aria-label", l.close_source);
    this.values.replaceChildren();
    if (kind === "weather") {
      for (const [label, value] of stationValues(source, this.hass, l)) {
        const field = element("div");
        field.append(
          element("dt", undefined, label),
          element("dd", undefined, value),
        );
        this.values.append(field);
      }
      this.source.textContent = source.source_id;
    } else {
      const status = this.frame
        ? this.frame.camera?.availability
        : source.availability;
      this.source.textContent = `${l.camera_status}: ${status === "videoOrImagesAvailable" ? l.camera_available : (status ?? l.missing)}`;
    }
    this.message.textContent = l[this.imageMessage] ?? "";
  }

  async loadImage() {
    if (!this.selected || this.pending) return;
    const request = {};
    this.pending = request;
    this.clearImage();
    this.imageMessage = "camera_loading";
    this.render();
    try {
      const frame = await this.hass.callWS({
        type: "vegvesen/route_camera",
        ...routeTarget(this.config),
        source_id: this.selected.source.source_id,
        camera_distance_m: this.config.camera_distance_m ?? 250,
      });
      if (this.pending !== request) return;
      this.frame = frame;
      if (!frame.content || frame.content_type !== "image/jpeg")
        throw Error("No image");
      const image = element("img", "camera-image");
      image.hidden = true;
      image.alt = this.selected.name;
      image.onload = () => {
        if (this.image !== image) return;
        image.hidden = false;
        this.imageMessage = undefined;
        this.render();
      };
      image.onerror = () => {
        if (this.image !== image) return;
        this.imageMessage = "camera_unavailable";
        this.render();
      };
      this.image.replaceWith(image);
      this.image = image;
      image.src = `data:image/jpeg;base64,${frame.content}`;
    } catch {
      if (this.pending !== request) return;
      this.imageMessage = "camera_unavailable";
    } finally {
      if (this.pending === request) {
        this.pending = undefined;
        this.render();
      }
    }
  }

  clearImage() {
    this.image.onload = this.image.onerror = null;
    this.image.removeAttribute("src");
    this.image.hidden = true;
  }

  close(collapse = true) {
    if (collapse) this.sources.collapse();
    clearInterval(this.timer);
    this.timer =
      this.selected =
      this.pending =
      this.frame =
      this.imageMessage =
        undefined;
    this.panel.hidden = true;
    this.clearImage();
  }

  stop() {
    this.data.stop();
    this.snapshot = this.error = undefined;
    this.close();
    this.removeMarkers();
  }

  removeMarkers() {
    this.sources.remove();
  }
}
