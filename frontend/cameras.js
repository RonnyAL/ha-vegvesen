import { pointToLineDistance } from "@turf/point-to-line-distance";
import { lines } from "./data.js";

// HA provides only the states this user can read. Never fetch a source image
// directly or infer identity from an entity name or user-editable device label.
export const cameraSources = (hass) =>
  Object.values(hass?.states ?? {}).filter((state) => {
    const { source_id, latitude, longitude } = state.attributes;
    return (
      state.entity_id.startsWith("camera.") &&
      hass.entities?.[state.entity_id]?.platform === "vegvesen" &&
      typeof source_id === "string" &&
      Number.isFinite(latitude) &&
      Math.abs(latitude) <= 90 &&
      Number.isFinite(longitude) &&
      Math.abs(longitude) <= 180
    );
  });

export function nearbyCameras(cameras, geometry, distance) {
  const parts = lines(geometry).map((coordinates) => ({
    type: "LineString",
    coordinates,
  }));
  return cameras.filter(({ attributes: { longitude, latitude } }) =>
    parts.some(
      (part) =>
        pointToLineDistance([longitude, latitude], part, {
          units: "meters",
          method: "geodesic",
        }) <= distance,
    ),
  );
}

export const cameraAvailable = (state) =>
  state && !["unavailable", "unknown"].includes(state.state);

export const cameraName = (state) =>
  state.attributes.friendly_name || state.attributes.source_id;

// Only HA's own camera proxy is eligible. This also prevents a state attribute
// from redirecting an authenticated image request to an external provider.
export function cameraPicture(state, hass) {
  const path = state?.attributes.entity_picture;
  if (!cameraAvailable(state) || typeof path !== "string") return undefined;
  const expected = `/api/camera_proxy/${state.entity_id}?`;
  return path.startsWith(expected) ? hass.hassUrl(path) : undefined;
}
