// A route already has a HA device. Use its stable ID rather than a summary sensor.
export const routeSchema = [
  {
    name: "device_id",
    required: true,
    selector: {
      device: {
        filter: [{ manufacturer: "Statens vegvesen", model: "Route forecast" }],
      },
    },
  },
];

export function editorConfig(config, hass) {
  const device_id =
    config.device_id || hass?.entities?.[config.entity]?.device_id;
  if (!device_id) return { ...config };
  const result = { ...config, device_id };
  delete result.entity;
  return result;
}

export function stubConfig(hass) {
  const devices = Object.values(hass.devices ?? {}).filter(
    (device) =>
      device.model === "Route forecast" &&
      Object.values(hass.entities ?? {}).some(
        (entity) =>
          entity.device_id === device.id && entity.platform === "vegvesen",
      ),
  );
  // Never silently choose one of several routes.
  return { device_id: devices.length === 1 ? devices[0].id : "" };
}
