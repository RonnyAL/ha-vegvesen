// A route already has a HA device. Use its stable ID rather than a summary sensor.
export const routeSchema = (labels) => [
  {
    name: "device_id",
    required: true,
    selector: {
      device: {
        filter: [{ manufacturer: "Statens vegvesen", model: "Route forecast" }],
      },
    },
  },
  { name: "title", selector: { text: {} } },
  {
    name: "height",
    selector: {
      number: {
        min: 240,
        max: 1000,
        step: 10,
        mode: "box",
        unit_of_measurement: "px",
      },
    },
  },
  {
    name: "default_mode",
    selector: {
      select: {
        mode: "dropdown",
        options: [
          { value: "condition", label: labels.condition },
          { value: "slip", label: labels.slip },
        ],
      },
    },
  },
  { name: "legend_expanded", selector: { boolean: {} } },
];

export function editorConfig(config, hass) {
  const defaults = {
    height: 400,
    default_mode: "condition",
    legend_expanded: true,
  };
  const device_id =
    config.device_id || hass?.entities?.[config.entity]?.device_id;
  if (!device_id) return { ...defaults, ...config };
  const result = { ...defaults, ...config, device_id };
  delete result.entity;
  return result;
}

export function changedConfig(config, values) {
  const result = { ...config, ...values };
  delete result.entity;
  // Clearing an optional field restores its default instead of storing null.
  for (const key of ["title", "height", "default_mode", "legend_expanded"]) {
    if (result[key] == null || result[key] === "") delete result[key];
  }
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
