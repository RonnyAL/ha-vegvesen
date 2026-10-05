import { SourceMarkers, element, icon } from "./source-markers.js";
import {
  cameraSources,
  nearbyCameras,
  cameraAvailable,
  cameraName,
  cameraPicture,
} from "./cameras.js";

// Camera images and state updates use HA's existing entities and cached proxy.
// Only an open image refreshes the HA proxy; it never polls the source provider.
export class CameraOverlay {
  constructor(frame, onOpen) {
    this.onOpen = onOpen;
    this.sources = new SourceMarkers(
      (item, keyboard) => {
        this.onOpen();
        this.select(item.camera);
        if (keyboard) this.closeButton.focus({ preventScroll: true });
      },
      () => {
        this.close(false);
        this.onOpen();
      },
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
    this.message = element("div", "camera-message");
    this.message.setAttribute("role", "status");
    this.source = element("div", "camera-source");
    this.panel.append(heading, this.image, this.message, this.source);
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
    if (!visible || !geometry || !hass?.connected) {
      this.close();
      this.removeMarkers();
      return;
    }
    this.sources.update(
      this.cameras.map((camera) => ({
        id: `camera:${camera.attributes.source_id}`,
        coordinates: [camera.attributes.longitude, camera.attributes.latitude],
        name: cameraName(camera),
        icon: "mdi:camera",
        camera,
      })),
      map,
      labels,
    );
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
    if (!this.entityId) return;
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

  close(collapse = true) {
    if (collapse) this.sources.collapse();
    clearInterval(this.timer);
    this.timer = undefined;
    this.sourceId = this.entityId = undefined;
    this.panel.hidden = true;
    this.clearImage();
  }

  removeMarkers() {
    this.sources.remove();
  }
}
