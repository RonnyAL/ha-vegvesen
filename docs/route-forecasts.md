# Route forecasts: first milestone

Implemented in 0.6.0. Routes prioritize **forecast road conditions (føreforhold)**,
independently of measured weather stations. [User instructions](../README.md#route-forecasts-føreforhold).

## Verified public services

Investigated on 2026-10-04 against official documentation and actual responses.
No credentials were supplied to the endpoints below.

- [Routing OpenAPI](https://www.vegvesen.no/ws/no/vegvesen/ruteplan/routingservice_v3_0/open/routingService/swagger/v1/swagger.json)
  and [routing documentation](https://labs.vegdata.no/ruteplandoc/).
- [Road-routing catalogue](https://dataut.vegvesen.no/nb/dataset/ruteplandata-bil):
  NLOD and a stated limit of 2,500 calls/day. The catalogue describes registration
  and credentials; the documented `/open/` endpoint used here worked without
  them and its inspected OpenAPI did not declare an authentication requirement.
  This is evidence for this endpoint, not a guarantee about every routing service.
- [OGC collections](https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/collections)
  and [official map-layer overview](https://www.vegvesen.no/fag/teknologi/apne-data/et-utvalg-apne-data/ogc-karttjenester/kartlag/).
  The latter identifies Vegvær observations and forecasts; optional registration
  is not required for access.

Routing uses GET:

```text
https://www.vegvesen.no/ws/no/vegvesen/ruteplan/routingservice_v3_0/open/routingservice/api/Route/best
  ?Stops=10.395,63.43;9.846,63.305
  &InputSRS=EPSG_4326&OutputSRS=EPSG_4326&ReturnFields=Geometry&Lang=Norwegian
```

This public Trondheim–Orkanger example returned E6/E39, 41,811 metres, with
21 line features. `routeName`, `statistic.totalLength`, `isObstructed` and
complete geometry are validated. The service's transient `routeId` is not a
saved-route identity. Separate line parts are retained without bridging gaps.
An actual off-network request returned HTTP 404 with lowercase `code: 9200`.
Documented no-route/off-network codes are distinguished from timeout/overload
errors, which must not be reported as proof that no road route exists.

Forecasts use the verified collection
[`vegvar_1_0:vv_road_prognosis_V2`](https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/collections/vegvar_1_0:vv_road_prognosis_V2).
Its nationwide response had approximately 2.87 million records, including
multiple forecast hours. Runtime never requests this unfiltered dataset.
The items query uses `f=application/json`, `limit=500`, a geographic `bbox`,
`filter-lang=cql2-text`, and
`filter=FORECAST_TIME = TIMESTAMP('<timezone-aware ISO timestamp>')`.
Both spatial and time filtering and continuation links were verified live.

The collection's `queryables` endpoint returned HTTP 500 during investigation;
[WFS DescribeFeatureType](https://ogckart-sn1.atlas.vegvesen.no/vegvar_1_0/ows?service=WFS&version=2.0.0&request=DescribeFeatureType&typeNames=vegvar_1_0:vv_road_prognosis_V2)
provided the field schema. Source categories were cross-checked against official
[WMS styles](https://ogckart-sn1.atlas.vegvesen.no/vegvar_1_0/wms?service=WMS&version=1.1.1&request=GetStyles&layers=vv_road_prognosis_V2&styles=forecast_road_condition).

| Source field | Meaning/use |
| --- | --- |
| `ROAD_SEGMENT_ID` | Integer source segment identifier; zero is valid |
| `FORECAST_TIME` | Timezone-aware valid hour; combined with segment ID for record uniqueness |
| Feature geometry | Geographic MultiLineString; missing geometry cannot be matched |
| `ROAD_CONDITION` | Source category or null; original code retained in attributes/action |
| `SLIP_RISK` | Source low/medium/high category or null, without custom grading |
| `ROAD_TEMPERATURE`, `ROAD_TEMPERATURE_UOM` | Numeric/null, verified °C; route minimum/maximum use available values |
| `SNOW_AMOUNT`, `SNOW_AMOUNT_UOM` | Source value in cm, available unchanged through the action |
| `SNOW_PRECIPITATION`, `RAIN_PRECIPITATION`, `PRECIPITATION_AMOUNT` | Source values with their unit fields (cm, mm, mm), available through the action |

Verified road-condition codes: `NoNewPrecipitation`, `WetRoadSurface`,
`IceOrFrost`, `SnowCover`, `DriftingSnow`, `ErrorOrNoData`.
`ErrorOrNoData` and null produce unknown/incomplete summaries; the action and
category attributes preserve source codes. Future string codes remain usable,
untranslated. Enum translation keys are HA-compatible lowercase names; this
changes presentation, not the underlying category.

## Polling, matching and lifecycle

Each route owns a local UUID, saved geometry, corridor distance and forecast
hour offset in a `route` subentry under the existing parent. Reconfiguration
preserves entity/device identity. Explicit recalculation requests fresh road
proposals; routine polling and editing only the name/corridor/hour offset reuse
geometry. From 0.6.1, native dropdowns offer existing `zone.*` entities by friendly name
and ID, plus a translated manual-map option. Only manual endpoints render maps.
The map forms use HA's native location selectors with explicit home-location
initial values; required empty location selectors otherwise fail to render in
the tested HA frontend. Locations remain in HA's configuration and are sent to
the public routing service when calculating; no user locations are tracked here.
Zone entity IDs and names are retained alongside the resolved coordinates. A
moved zone is resolved again when applying settings or explicitly recalculating;
normal polling uses the saved geometry. Deleted/unavailable/malformed zones cause
an editable field error, never a silent switch to home coordinates. Existing
0.6.0 coordinate-only routes remain editable without migration or changed IDs.
The dropdown and map selectors exist in the minimum HA version; the newer
choose-selector widget does not, so it is not required.

From 0.6.2, a route fetches immediately on setup, then just after each UTC hour
and half-hour. This is an integration choice, not a verified source publication
cadence. Target time is current UTC hour plus the selected offset. For offset 1,
a request at 14:35 selects 15:00 and the request just after 15:00 selects 16:00.
The valid time is neither a fetch timestamp nor a verified issue timestamp.
Unchanged snapshots suppress redundant entity updates; a new selected hour still
updates the timestamp. Empty matches retain unknown forecast states.

The coordinator recalculates its next interval when HA schedules a refresh,
keeping manual refreshes from shifting the clock alignment. A one-second margin
avoids HA timer rounding firing just before the hour. If a successful request
straddles an hour boundary, one short catch-up refresh selects the new hour.
HA's existing timer remains the sole scheduler: `Retry-After` takes precedence,
disabled polling is respected, and unloading/removing the last listener cancels
scheduled work. Normal failed requests retry at the next boundary. Initial
all-family failures still use HA's setup retry. This follows the coordinator
lifecycle described in [HA's fetching-data guide](https://developers.home-assistant.io/docs/integration_fetching_data/);
HA's [Tibber coordinator](https://github.com/home-assistant/core/blob/2026.9.4/homeassistant/components/tibber/coordinator.py)
also adjusts intervals to clock boundaries. Both supported HA versions are tested.

No documented or advertised push/subscription endpoint was found for this
road-segment feed in the [OGC landing page](https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/),
[conformance declaration](https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/conformance)
or official map-layer documentation on 2026-10-04. The advertised
[`openapi` endpoint](https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/openapi)
returned HTTP 500, limiting verification of the complete API inventory. The
separate [weather forecast dataset](https://dataut.vegvesen.no/nb/dataset/vaerdata-prognose)
describes point forecasts via XML REST, not a verified push replacement for road
segments. Clock-aligned polling is therefore used; it is not a source event feed.

One route's failure does not stop weather, cameras or other routes. Removing a
route unloads its polling and entities. Entry reload detects both subentry
membership and data/title changes.

Geometry work runs in HA's executor using pinned PyProj 3.8.0 and Shapely 2.1.2.
A local azimuthal equidistant projection constructs the metric buffer; its
outward-rounded WGS84 bounding rectangle limits the server query. After complete
pagination, local geometry intersection excludes roads outside the corridor.
The public example returned 935 records in the rectangle and 324 intersecting
a 100-metre corridor at the tested hour. Counts and source coverage can change.

The shared API reader enforces the original query on continuation links,
unique record IDs, reported counts, loop protection, an overall 30-second
request deadline and a page bound. HTTP errors, malformed records, wrong target
hours and incomplete pagination fail the refresh. No intermediate page is
published. HTTP 429 retry hints are retained. No source snapshot token was
verified: these checks detect many changes during pagination but cannot prove
all pages came from one atomic upstream publication.

Six small sensor states summarize matched segments. There is no custom route
risk score or severity ranking. Missing values remain explicit; an entirely
empty match has count zero and unknown other sensors. Complete pagination does
not establish complete road coverage. `vegvesen.get_route_forecasts` returns
full cached segment geometry/properties on demand, avoiding recorder growth
from large state attributes. It rejects unavailable routes.

## Limits and future ownership

- This version uses two endpoints and the service's proposed roads. No via
  points, GPX import, route-line preview, automatic rerouting or incidents.
- Matching is geographic, not road-network topology: side roads, opposite
  directions and grade-separated crossings can be included. Buffer distances
  are locally projected; very long routes have greater projection distortion
  and bounding-box request cost. Large results can exceed the deadline.
- No guaranteed geographic coverage, road-segment forecast horizon,
  publication cadence, issue timestamp or source atomicity was verified.
  A requested hour with no records yields unknown, not an inferred forecast.
- The inspected road-segment forecast material did not establish a specific
  licence statement for that collection. SVV attribution is retained; do not
  infer its terms solely from a different weather dataset's NLOD statement.
- Minimum HA remains 2025.12.0, justified by the existing subentry/lifecycle and
  `UpdateFailed(retry_after=...)` APIs. Routes add no newer HA requirement.
  Both locked environments run the same tests.
- Independent routes have independent geometry/corridors; no area can restrict
  them. This milestone creates logical route devices, not physical station or
  camera copies. Overlapping routes currently make independent forecast queries.
  If future monitors automatically select physical sources, model explicit and
  monitor ownership separately, retain one source-ID identity, and remove a
  physical source only when no owner remains. Area ownership must be independent
  of route ownership. No monitor-ownership framework is implemented now.
