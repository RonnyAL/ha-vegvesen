import * as maplibregl from "maplibre-gl";
import {
  cameraSources,
  nearbyCameras,
  cameraAvailable,
  cameraName,
  cameraPicture,
} from "./cameras.js";

const element = (tag, className, text) => {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  if (tag === "button") item.type = "button";
  return item;
};
const icon = (name) => {
  const item = element("ha-icon");
  item.setAttribute("icon", name);
  item.setAttribute("aria-hidden", "true");
  return item;
};

// Camera images and state updates use HA's existing entities and cached proxy.
// Only an open image refreshes the HA proxy; it never polls the source provider.
export class CameraOverlay {
  constructor(frame, onOpen) {
    this.onOpen = onOpen;
    this.markers = new Map();
    this.panel = element("section", "camera-panel");
    this.panel.hidden = true;
    const heading = element("div", "panel-heading");
    this.title = element("h3");
    this.closeButton = element("button", "panel-close");
    this.closeButton.append(icon("mdi:close"));
    this.closeButton.onclick = () => {
      this.close();
      this.origin?.focus({ preventScroll: true });
    };
    heading.append(this.title, this.closeButton);
    this.choices = element("div", "camera-choices");
    this.image = element("img", "camera-image");
    this.image.hidden = true;
    this.message = element("div", "camera-message");
    this.message.setAttribute("role", "status");
    this.source = element("div", "camera-source");
    this.panel.append(
      heading,
      this.choices,
      this.image,
      this.message,
      this.source,
    );
    frame.append(this.panel);
  }

  update(hass, geometry, distance, visible, labels, map) {
    Object.assign(this, { hass, labels });
    const cameras = hass?.connected ? cameraSources(hass) : [];
    const positions = JSON.stringify(
      cameras.map(({ entity_id, attributes: a }) => [
        entity_id,
        a.longitude,
        a.latitude,
      ]),
    );
    if (
      geometry !== this.geometry ||
      positions !== this.positions ||
      distance !== this.distance
    ) {
      this.nearIds = new Set(
        geometry
          ? nearbyCameras(cameras, geometry, distance).map((s) => s.entity_id)
          : [],
      );
      Object.assign(this, { geometry, positions, distance });
    }
    this.cameras = cameras.filter((s) => this.nearIds.has(s.entity_id));
    this.count = this.cameras.length;
    if (map !== this.map) {
      this.removeMarkers();
      this.map = map;
    }
    if (!visible || !geometry || !hass?.connected) {
      this.close();
      this.removeMarkers();
      return;
    }
    // Directions at the same source position share a marker, not an image/entity.
    const groups = new Map();
    for (const camera of this.cameras) {
      const { longitude, latitude } = camera.attributes;
      const key = `${longitude},${latitude}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(camera);
    }
    for (const [key, marker] of this.markers) {
      if (!groups.has(key)) {
        marker.remove();
        this.markers.delete(key);
      }
    }
    if (map)
      for (const [key, group] of groups) {
        let marker = this.markers.get(key);
        if (!marker) {
          const button = element("button", "camera-marker");
          button.append(icon("mdi:camera"));
          marker = new maplibregl.Marker({ element: button })
            .setLngLat(key.split(",").map(Number))
            .addTo(map);
          this.markers.set(key, marker);
        }
        const button = marker.getElement();
        button.title = group.map(cameraName).join(" / ");
        button.setAttribute("aria-label", button.title);
        button.onclick = (event) => {
          event.stopPropagation();
          this.onOpen();
          this.origin = button;
          this.group = group.map((s) => s.attributes.source_id);
          this.select(group[0]);
        };
      }
    this.render();
  }

  select(camera) {
    this.sourceId = camera.attributes.source_id;
    this.entityId = camera.entity_id;
    this.imageState = undefined;
    // Camera frames can change without an HA state change. As with a native
    // picture card, refresh only the displayed image, from HA's cached proxy.
    this.timer ??= setInterval(() => {
      if (document.visibilityState === "hidden") return;
      this.imageState = undefined;
      this.render();
    }, 60000);
    this.render();
  }

  render() {
    const current = this.cameras?.find(
      (s) => s.attributes.source_id === this.sourceId,
    );
    if (current) this.entityId = current.entity_id;
    const state = this.hass?.states?.[this.entityId];
    // Removal, permission loss and replacement must clear the selected image.
    if (
      !state ||
      (cameraAvailable(state) && !current) ||
      this.hass.entities?.[this.entityId]?.platform !== "vegvesen" ||
      (state.attributes.source_id &&
        state.attributes.source_id !== this.sourceId)
    ) {
      this.close();
      return;
    }
    const l = this.labels;
    this.panel.hidden = false;
    this.panel.setAttribute("aria-label", l.road_cameras);
    this.title.textContent = cameraName(state) || this.entityId;
    this.closeButton.title = l.close_camera;
    this.closeButton.setAttribute("aria-label", l.close_camera);
    const focusedSource =
      this.panel.getRootNode().activeElement?.dataset?.cameraSource;
    this.choices.replaceChildren();
    const group = this.cameras.filter((s) =>
      this.group?.includes(s.attributes.source_id),
    );
    if (group.length > 1)
      for (const camera of group) {
        const choice = element(
          "button",
          undefined,
          camera.attributes.orientation || cameraName(camera),
        );
        choice.setAttribute(
          "aria-pressed",
          String(camera.attributes.source_id === this.sourceId),
        );
        choice.dataset.cameraSource = camera.attributes.source_id;
        choice.onclick = () => this.select(camera);
        this.choices.append(choice);
        if (focusedSource === camera.attributes.source_id)
          choice.focus({ preventScroll: true });
      }
    const available = cameraAvailable(state);
    const status = state.attributes.source_availability;
    this.source.textContent = `${l.camera_status}: ${status === "videoOrImagesAvailable" ? l.camera_available : (status ?? l.missing)}`;
    const url = cameraPicture(state, this.hass);
    if (this.imageState !== state) {
      this.clearImage();
      this.imageState = state;
      this.imageMessage =
        available && url ? "camera_loading" : "camera_unavailable";
      if (url) {
        const image = element("img", "camera-image");
        image.hidden = true;
        image.alt = cameraName(state);
        image.referrerPolicy = "no-referrer";
        image.onload = () => {
          if (this.image !== image) return;
          image.hidden = false;
          this.imageMessage = undefined;
          this.message.textContent = "";
        };
        image.onerror = () => {
          if (this.image !== image) return;
          image.hidden = true;
          this.imageMessage = "camera_unavailable";
          this.message.textContent = this.labels.camera_unavailable;
        };
        this.image.replaceWith(image);
        this.image = image;
        image.src = `${url}&time=${Date.now()}`;
      }
    }
    this.message.textContent = l[this.imageMessage] ?? "";
  }

  clearImage() {
    this.image.onload = this.image.onerror = null;
    this.image.removeAttribute("src");
    this.image.hidden = true;
    this.imageState = undefined;
  }

  close() {
    clearInterval(this.timer);
    this.timer = undefined;
    this.sourceId = this.entityId = undefined;
    this.panel.hidden = true;
    this.clearImage();
  }

  removeMarkers() {
    this.markers.forEach((marker) => marker.remove());
    this.markers.clear();
    this.map = undefined;
  }
}
