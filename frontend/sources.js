import { routeTarget } from "./data.js";

export const sourceRequest = (config) => ({
  type: "vegvesen/subscribe_route_sources",
  ...routeTarget(config),
  show_cameras: config.show_cameras ?? false,
  show_weather: config.show_weather ?? false,
  camera_distance_m: config.camera_distance_m ?? 250,
  weather_distance_m: config.weather_distance_m ?? 250,
});

export const sourceItems = (snapshot) =>
  ["cameras", "weather"].flatMap((kind) =>
    snapshot?.[kind]?.status === "ready"
      ? snapshot[kind].items.map((source) => ({
          id: `${kind}:${source.source_id}`,
          coordinates: [source.longitude, source.latitude],
          name: source.orientation
            ? `${source.name} — ${source.orientation}`
            : source.name,
          icon: kind === "cameras" ? "mdi:camera" : "mdi:weather-partly-cloudy",
          kind,
          source,
        }))
      : [],
  );

// Visual groups are not physical sites: retain each source's identity, including
// same-name cameras pointing in different directions. Weather comes first so a
// station is not hidden below a long list of camera directions on a small map.
export function sourceSections(items, labels) {
  return [
    ["weather", labels.weather_stations],
    ["cameras", labels.road_cameras],
  ].flatMap(([kind, label]) => {
    const members = items.filter((item) => item.kind === kind);
    if (!members.length) return [];
    const names = new Map();
    for (const item of members)
      names.set(item.name, (names.get(item.name) ?? 0) + 1);
    return [
      {
        kind,
        label: `${label} (${members.length})`,
        icon: members[0].icon,
        items: members.map((item) => ({
          ...item,
          heading: item.source.name,
          detail: [
            item.source.orientation,
            names.get(item.name) > 1 ? item.source.source_id : undefined,
          ]
            .filter(Boolean)
            .join(" · "),
        })),
      },
    ];
  });
}

export function stationValues(source, hass, labels) {
  const fahrenheit = hass.config?.unit_system?.temperature === "°F";
  const value = source.air_temperature;
  // Unit conversion is presentation only; retain the exact source value in data.
  const temperature =
    value == null
      ? labels.missing
      : `${new Intl.NumberFormat(hass.locale?.language, { maximumFractionDigits: 3 }).format(fahrenheit ? value * 1.8 + 32 : value)} ${fahrenheit ? "°F" : "°C"}`;
  const time =
    source.measurement_time == null
      ? labels.missing
      : new Intl.DateTimeFormat(hass.locale?.language, {
          dateStyle: "short",
          timeStyle: "short",
          timeZone: hass.config?.time_zone,
        }).format(new Date(source.measurement_time));
  return [
    [labels.air_temperature, temperature],
    [labels.observation_time, time],
  ];
}
