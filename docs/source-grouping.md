# Camera and weather-station grouping

## Observed co-location

On 2026-10-06 at 07:47 UTC, complete responses from Statens vegvesen's
[WeatherSimple_v2](https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/collections/datex_3_1:WeatherSimple_v2/items?f=application/json&limit=500)
and [CctvSimple_v2](https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/collections/datex_3_1:CctvSimple_v2/items?f=application/json&limit=500)
contained 468 weather stations and 895 camera records. Directional cameras are
separate records; those cameras had 737 distinct coordinate pairs.

| Station's nearest camera | Stations | Share of stations |
| --- | ---: | ---: |
| Identical coordinates | 299 | 63.9% |
| Within 1 metre | 392 | 83.8% |
| Within 10 metres | 415 | 88.7% |
| Within 25 metres | 423 | 90.4% |

Counts are cumulative and describe this snapshot, not an API guarantee. The
comparison used the integration's strict paginated client, then WGS84 geodesic
distances (`pyproj.Geod.inv`) from each station to every camera. No camera images
were fetched. To reproduce, retrieve all pages of both collections with
`VegvesenApiClient.async_get_weather()` / `async_get_cameras()`, retain the supplied
longitude/latitude pairs, and count the minimum distance per station at each
threshold above. Weather and camera catalogues can change independently.

Identical coordinates alone miss many near-identical positions: station
`1029008` (Fv 450 Hunnedalen) and camera `1029008_1` differ by about 0.04 metres;
`1429032` (E39 Årbergsdalen) and `1429032_1` differ by about 0.45 metres. Proximity
supports displaying them together but does not prove shared physical ownership.
Names and similar ID prefixes are not used to infer a common device or site.

## Presentation

The common case warrants mixed groups rather than separate overlapping markers
for each source family. Grouping remains based on 40 screen pixels, as in 0.9.1:
zooming separates distinct nearby positions; exact coincidences stay together.
The group centre is only a display position. Source coordinates and identities
are unchanged, including when routes overlap. Discovery and caching remain shared
and failure handling stays independent; no physical entities are created.

The design uses three levels of detail:

1. A collapsed marker shows a count and the kinds present. Mixed groups show both
   weather and camera icons. Shape and icons carry the distinction in light and
   dark themes; colors do not imply a road-risk assessment.
2. Tapping reveals full-width rows, with weather stations first and cameras below.
   Mixed lists have section labels/counts. A single-kind group uses its kind as
   the heading, without repeating a section header. Names are primary, camera
   directions secondary. Otherwise indistinguishable names also show source IDs.
3. Choosing a row opens the existing observation or image details. Only selecting
   a camera requests its image. Neither action fits or zooms the map.

The list opens in a bounded in-map panel, matching the source-detail panels.
An anchored popup would restrict its height to the space above or below the
marker, hiding camera choices even in a typical three-source group. The panel
uses the available height without moving the map and leaves the controls and
attribution accessible. The expanded marker gains a selection outline.

Rows are at least 48 pixels high, markers and close controls at least 44 pixels.
Long names wrap instead of being cut off; large groups scroll within the map.
Keyboard users can open with Enter/Space, tab through native buttons and return
with Escape. Metadata updates retain buttons and focus. Closing source details
restores the group and the chosen row for keyboard users. The existing eight-second
idle collapse waits while focus or hover remains inside the list.

## Official design references

- HA 2026.10.0b0 pins frontend 20260930.0. Its
  [`ha-map` cluster bubbles](https://github.com/home-assistant/frontend/blob/20260930.0/src/components/map/ha-map.ts)
  show member icons inside rounded, themed containers. This card retains that
  visual language but opens groups on tap without changing the viewport.
- Material's [list component guidance](https://github.com/material-components/material-web/blob/main/docs/components/list.md)
  describes leading icons, headline/supporting text and button items. Full-width
  rows follow that hierarchy and give long names more space than the previous
  two-column tiles. The implementation uses semantic lists and native buttons,
  without importing HA's internal components or adding another UI library.
- WAI's [disclosure pattern](https://www.w3.org/WAI/ARIA/apg/patterns/disclosure/)
  specifies button semantics, `aria-expanded` and Enter/Space activation.
  The [enhanced target-size guidance](https://www.w3.org/WAI/WCAG22/Understanding/target-size-enhanced.html)
  recommends 44-pixel targets at AAA; this is not the AA minimum.

See [route-card architecture](route-card.md) for discovery, lifecycle and caching,
and [validation](validation.md) for the packaged browser scenarios. Browser touch
emulation does not replace testing in physical companion apps.
