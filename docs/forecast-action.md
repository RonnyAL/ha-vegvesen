# Route forecast action

`vegvesen.get_route_forecasts` is a native Home Assistant
[response action](https://developers.home-assistant.io/docs/dev_101_services/#response-data).
It queries an existing saved route; it does not create a route, change its forecast
offset, update its entities or switch the map to another hour.

## Inputs and response

| Input | Meaning |
| --- | --- |
| `device_id` | Required: the saved route device, selectable by name in the action editor |
| `forecast_time` | Optional date/time; omit to return the last successful sensor snapshot without I/O |
| `include_segments` | Defaults to `true`; set `false` for a compact summary without segment geometry |

An explicit time selects its containing UTC hour. For example, 07:45 at UTC+02:00
selects 05:00 UTC. Unzoned dates follow HA's configured time zone. During the
autumn daylight-saving transition, use an explicit offset to distinguish the
two occurrences of a local hour; an unzoned date follows HA's normal conversion.
The allowed range is the current UTC hour through 24 hours ahead, inclusive.
This is an integration request limit, **not a guarantee of source availability**.

The response is a dictionary suitable for a
[response variable](https://www.home-assistant.io/docs/scripts/perform-actions/#use-templates-to-handle-response-data):

| Key | Meaning |
| --- | --- |
| `route` | Saved route name |
| `forecast_time` | Selected forecast hour, ISO 8601 UTC |
| `requested_time` | Input time converted to UTC, or `null` when omitted |
| `retrieved_at` | Retrieval completion time in UTC, preserved on a cache hit; not a source issue time |
| `summary.matched_segments` | Number of returned records intersecting this route's corridor |
| `summary.road_condition.source_categories` | Counts keyed by unchanged source codes, including unknown codes |
| `summary.road_condition.missing_segments` | Null or `ErrorOrNoData` condition records |
| `summary.road_condition.unrecognized_segments` | Records with an unrecognized, non-missing condition code |
| `summary.slipperiness` | Same counts as road condition, plus `highest_known`: `low`, `medium`, `high` or `null` |
| `summary.road_temperature` | `minimum`, `maximum`, `unit` (`°C`) and `missing_segments` |
| `segments` | When enabled, GeoJSON Features containing the unchanged source geometry and properties |

Null temperatures are omitted from extrema. Zero and unusual numeric values are
preserved. Missing temperatures remain null, never zero. Unknown slipperiness
codes are retained in counts and are not assigned a severity. `ErrorOrNoData`
remains present in raw category counts as well as the missing-data count.

A complete empty response is valid: `matched_segments` is zero, categories are
empty, temperatures and highest known grade are null. It says nothing about
safety. Even a nonempty response does not establish complete route coverage;
counts are source records, not distance. Missing geometry cannot be matched to
the corridor, and side roads may intersect it.

Malformed or incomplete pages, a wrong forecast hour, request failure or timeout
raise an action error. No partial result is returned. Uncached queries made while the
source's `Retry-After` cooldown is active fail without another network request.
Route removal, disabling or unloading also prevents a response from its old
runtime. An omitted time retains the original action behavior: a failed sensor
refresh is reported as unavailable instead of returning an old snapshot.

## Morning briefing example

Paste [route_forecast_briefing.yaml](../examples/route_forecast_briefing.yaml) into
a new automation's YAML editor. Replace the route device placeholder and adjust
the 06:30 trigger and 07:00 departure. It uses HA's
[persistent notification](https://www.home-assistant.io/integrations/persistent_notification/)
action; a mobile notification action can be substituted.

The example reports source categories and gaps. A failed request produces an
explicit failure notice; an unpublished hour produces a no-data notice. It
does not make a safe/unsafe judgment. The example is executed by HA's actual
script engine in the mocked test suite, including null/zero, empty and failure
cases.

## Retrieval and lifecycle

Each saved route shares a cache between explicit action queries and its existing
coordinator. A cached hour expires after five minutes; at most four complete
snapshots are retained. Concurrent requests for the same route/hour await one
request. Different hours are serialized per route. The 40-second overall bound
includes queueing and geographic matching; the existing transport has a
30-second deadline covering all pages. Scheduled and manual sensor refreshes
bypass cached results, while sharing any already-running query for their hour.
The existing hour/half-hour polling schedule remains unchanged.

An action query does not publish coordinator state or alter its availability.
Cancelling one caller does not cancel a request needed by another. Background
tasks belong to HA's config entry; unload cancels them and discards the cache.
Reconfiguration creates a new coordinator and geometry cache. Cache entries are
not persisted and are not shared between different saved routes. The existing
source-wide rate-limit cooldown still applies across routes.

The minimum remains HA 2025.12.0. Date/time and boolean selectors, response
actions, config-entry-owned background tasks and the existing coordinator APIs
are available there. No new frontend hooks, weather entities, custom scheduler
or forecast history store is introduced. A map time selector and multi-hour
timeline are future milestones.

## API feasibility check — 2026-10-06

Official [SVV layer documentation](https://www.vegvesen.no/fag/teknologi/apne-data/et-utvalg-apne-data/ogc-karttjenester/kartlag/)
describes Vegvær observations and forecasts. The
[OGC API landing page](https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/)
and [conformance document](https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/conformance)
advertise feature queries, bounding boxes and CQL2 filtering. The
[forecast collection](https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/collections/vegvar_1_0:vv_road_prognosis_V2)
provides a spatial extent but no guaranteed temporal horizon. Its
[WFS schema](https://ogckart-sn1.atlas.vegvesen.no/vegvar_1_0/ows?service=WFS&version=2.0.0&request=DescribeFeatureType&typeNames=vegvar_1_0:vv_road_prognosis_V2)
confirms forecast time, geometry and nullable source properties.

Live checks used the existing strict pagination client, with these parameters
on the collection's `/items` endpoint:

```text
f=application/json
limit=500
bbox=<saved route bounding box, including corridor>
filter-lang=cql2-text
filter=FORECAST_TIME = TIMESTAMP('<selected UTC hour>')
```

| Public test area | Requested hour | Complete result | Elapsed |
| --- | --- | --- | --- |
| Central Trondheim, small bounding box | +1 hour | 125 records | 0.27 s |
| Trondheim–Orkanger route, 100 m corridor | +1 hour | 935 records over two pages; 324 corridor matches | 2.23 s |
| Same route | +6 hours | 935 records over two pages; 324 corridor matches | 1.13 s |
| Central Trondheim, small bounding box | +24 hours | Empty complete response | 0.09 s |

These are observations, not performance or availability guarantees. The OpenAPI
and queryables endpoints returned HTTP 500 during the investigation. A guaranteed
forecast horizon, publication cadence and atomic publication across multiple
hours could not be verified. The implementation therefore reuses one bounded
spatial query for one exact hour; it does not download a nationwide time series,
assume every future hour exists, or infer unsupported temporal-range behavior.
