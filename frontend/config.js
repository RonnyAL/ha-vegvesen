// The map settings use the same preset names as HA 2026.10.0b0's map card.
export const MAP_STYLES = [
  "default",
  "colorful",
  "natural",
  "muted",
  "gray",
  "toner",
];
export const THEME_MODES = ["auto", "light", "dark"];
export const darkMode = (config, hass) =>
  config.theme_mode === "dark" ||
  (config.theme_mode !== "light" && !!hass?.themes?.darkMode);

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
    name: "",
    type: "expandable",
    title: labels.appearance,
    icon: "mdi:palette",
    schema: [
      {
        name: "",
        type: "grid",
        schema: [
          ...[
            ["theme_mode", THEME_MODES, labels.theme_modes],
            ["map_style", MAP_STYLES, labels.map_styles],
          ].map(([name, choices, names]) => ({
            name,
            selector: {
              select: {
                mode: "dropdown",
                options: choices.map((value) => ({
                  value,
                  label: names[value],
                })),
              },
            },
          })),
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
        ],
      },
    ],
  },
  ...[
    ["cameras", "camera", labels.road_cameras, "mdi:camera"],
    [
      "weather",
      "weather",
      labels.weather_stations,
      "mdi:weather-partly-cloudy",
    ],
  ].map(([kind, prefix, title, icon]) => ({
    name: "",
    type: "expandable",
    title,
    icon,
    schema: [
      { name: `show_${kind}`, selector: { boolean: {} } },
      {
        name: `${prefix}_distance_m`,
        selector: {
          number: {
            min: 1,
            max: 2000,
            step: 1,
            mode: "box",
            unit_of_measurement: "m",
          },
        },
      },
    ],
  })),
];

export function editorConfig(config, hass) {
  const defaults = {
    height: 400,
    default_mode: "condition",
    legend_expanded: false,
    map_style: "default",
    theme_mode: "auto",
    show_cameras: false,
    camera_distance_m: 250,
    show_weather: false,
    weather_distance_m: 250,
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
  for (const key of [
    "title",
    "height",
    "default_mode",
    "legend_expanded",
    "theme_mode",
    "map_style",
    "show_cameras",
    "camera_distance_m",
    "show_weather",
    "weather_distance_m",
  ]) {
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
