# Weather milestone: API and ownership

## Verified source behavior

The integration reads the [official OGC catalogue](https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/collections) and its `datex_3_1:WeatherSimple_v2` collection. The [official WFS/WMS notes](https://git.vegvesen.no/projects/DATEX2/repos/datex2-spesifications/browse/3.1/wfs-wms) describe the related DATEX layers. Field mappings below were checked against actual OGC JSON rather than assumed from older documentation.

Discovery uses `GET /ogc/features/v1/collections/datex_3_1:WeatherSimple_v2/items?f=application/json&limit=500`. Polling adds `filter-lang=cql2-text` and `filter=REFERENCE_ID IN ('source-id',...)`. Requests without credentials succeeded during investigation and live client verification on 2026-10-03. A plain property query does not reliably filter this service. Selection and polling therefore use CQL, and the client rejects unexpected station IDs.

| Source | Integration mapping |
| --- | --- |
| `properties.REFERENCE_ID` | Exact string ID; device `weather_station:<id>`; entities add the measurement key |
| `properties.LOCATION_DESCRIPTION` | Readable station name; dropdown also includes source ID |
| `properties.AIR_TEMPERATURE` | Numeric Celsius value, unchanged; null/missing → unknown |
| `properties.MEASUREMENT_TIME` | Offset-aware ISO timestamp; null/missing → unknown |
| `geometry.coordinates` | Longitude, latitude; parsed discovery metadata, no geographic restriction |
| `properties.ROAD_NUMBER` | Discovery metadata; not an entity in this milestone |

`numberMatched`, `numberReturned`, `features`, and `links[rel=next]` describe pagination. Follow the server links, including an observed extra empty terminal page. A refresh is accepted only after all pages succeed, counts agree, and source IDs are unique. Changed totals, missing pages, invalid JSON/schema, cycles, changed endpoint/filter, duplicate IDs, or failed requests fail the entire refresh. No partial accumulated result escapes the client. A complete response may legitimately omit a previously selected station; only that station becomes unavailable.

The coordinator polls selected IDs every ten minutes, matching the documented [weather publication cadence](https://www.vegvesen.no/en/fag/technology/open-data/a-selection-of-open-data/what-is-datex/publications/). Discovery snapshots are shared across configuration flows for up to 15 minutes, independently per source family; saving a selection still validates it with a fresh filtered request. See [discovery and geography](geographic-selection.md). Each refresh has a 30-second deadline for its whole request chain. HTTP 429 uses numeric or HTTP-date `Retry-After`, with a 60-second fallback for invalid/missing values; this is request backoff, not alteration of source observations. HA controls retries during initial setup. Other failures use the normal coordinator schedule.

The official [data catalogue](https://dataut.vegvesen.no/nb/dataservice/vaerdata-malinger-api) identifies NLOD licensing for weather data. Sensors expose the attribution **Data provided by Statens vegvesen**. The registered DATEX XML service and this credential-free OGC endpoint are different representations; the catalogue's license reference covers the underlying dataset, without a separately verified OGC-specific terms page.

No numerical request quota or atomic multi-page snapshot guarantee was verified. The client catches visible inconsistencies but cannot detect a same-count dataset replacement between pages. No staleness threshold is invented: observation time remains visible, even when old. Metadata renames update the integration's device name after a complete refresh; user device names and existing entity IDs remain unchanged. Saved source names also keep new entity IDs consistent when a station is absent at startup. Malformed schema is an explicit failure, not an inferred correction.

The shared client retains HTTP 429 cooldowns across setup retries, discovery,
manual refreshes and entry reloads. An early attempt raises the remaining delay
without HTTP; HA still owns all retry scheduling. Cooldowns are per collection
endpoint or image URL and last only for the current HA process. See the
[runtime review](runtime-review.md) for scope and lifecycle details.

## Current ownership and lifecycle

One singleton public-service parent owns typed runtime data. Camera support is now implemented; see the [camera milestone notes](camera-milestone.md) for its independent lifecycle. Each manual `weather_station` subentry owns one physical source device and its two sensor entities, registered with `config_subentry_id`. Duplicate source selections are rejected before and after selection I/O. The weather coordinator shares HA's HTTP session and handles only weather; its failures do not define the availability of the separate camera coordinator or route coordinators.

The first refresh completes before platforms are forwarded. Initial failures defer setup through HA's built-in retry when all selected source families fail; a healthy family can load while another recovers. Subsequent failures preserve the last internal data but mark entities unavailable. Null measurements on a present station are unknown. Add/remove subentry changes reload the parent to reconcile polling and entities. Platform unloading removes listeners; HA's config-entry cleanup shuts down coordinator timers and cancels an in-flight scheduled poll. The integration never closes HA's shared session. With zero station selections the client performs no requests and no entity listener schedules polling.

## Future monitors, without a framework now

Each future area must own its point/radius. Implemented [route forecasts](route-forecasts.md) already own independent geometry/corridors in route subentries, with logical route devices. A route may extend outside every area; there is no parent-wide boundary.

Overlapping monitors must reference a canonical physical source record keyed by `(source type, source ID)`, reusing its device/entities. They must not create another physical device or another copy of its measurements. HA [restricts a device to one config entry and at most one subentry](https://developers.home-assistant.io/blog/2026/07/21/device-registry-single-config-entry/); a device cannot be jointly owned by several monitor subentries.

Before implementing automatic discovery, define canonical ownership for automatically discovered sources and retention when manual selections/monitors disappear. The current manual station subentry is the sole owner. Future monitor references must not move that ownership on overlap. Explicit selections and monitor references may eventually need separate retention rules, with migration when required. Route forecasts do not automatically add physical stations or cameras. No reference-counting or automatic physical-source ownership framework is implemented; the route geometry engine only matches forecast road segments.

## Compatibility boundary

Tested: HA 2026.9.4 with CPython 3.14.8 and pytest-homeassistant-custom-component 0.13.367. The full suite also passes on the minimum HA 2025.12.0 with CPython 3.13.11 and test package 0.13.298. This minimum supports `UpdateFailed(retry_after=...)` as well as the subentry/runtime/lifecycle interfaces used here. The [2025.12 coordinator source](https://github.com/home-assistant/core/blob/2025.12.0/homeassistant/helpers/update_coordinator.py) and [config-entry source](https://github.com/home-assistant/core/blob/2025.12.0/homeassistant/config_entries.py) were checked. Its HA-managed Python requirement is distinct from this repository's primary development interpreter. See [validation details](validation.md).
