# Route-map beta: design and validation

The `feature/route-maps` branch adds static route previews and native image
entities. Version **0.8.0b1** is a GitHub prerelease, separate from `main` and the
stable **0.7.4** release. It does not change saved entry/subentry versions, route
geometry, forecast polling, existing sensor identities or source values.

Version **0.8.0b2** added an optional [interactive dashboard card](route-card.md)
with MapLibre/OSM vector tiles. **0.8.0b4** refines the static renderer as described
below; the original 0.8.0b1 browser/rollback results remain historical evidence.

## Verified Home Assistant capabilities

Checked against HA 2025.12.0, 2026.9.4 and 2026.10.0b0 and their pinned frontends:

- The native location selector selects points; it has no public route-overlay
  option. The ordinary map card displays locations, zones and history, without
  a supported arbitrary GeoJSON route-layer interface.
- Native config/subentry flow descriptions support Markdown images. The preview
  uses that mechanism, a `HomeAssistantView`, and HA's `async_sign_path` helper.
  No frontend patch, custom selector, synthetic entity or public `www` file is
  involved. Each signed URL expires after 30 minutes. Canceling, completing
  or returning to the overview invalidates its previous preview immediately, including
  a render still in progress. Reopening the overview creates a fresh signed URL.
- The [image entity API](https://developers.home-assistant.io/docs/core/entity/image/)
  provides native image access tokens, proxy endpoints, dashboard support and
  lifecycle. A route's image shares its existing service device and subentry.
  Its unique ID is `route:<route_id>:map`; HA owns its readable entity ID.
  `image_last_updated` changes in the coordinator callback, never during GET.
- HA 2026.10 beta's [MapLibre frontend](https://github.com/home-assistant/frontend/blob/20260930.0/src/components/map/ha-map.ts)
  uses OSM vector maps, with raster fallback. HA's
  [map_tiles integration](https://www.home-assistant.io/integrations/map_tiles/)
  proxies and caches those requests. Its cache/token implementation is internal;
  it does not provide a supported Python static-map renderer for integrations.
  The beta leaves native endpoint selection to HA and renders its static images
  separately using OSM raster tiles. The HA minimum remains **2025.12.0**.

## Rendering and source semantics

`route_map.py` projects and draws the selected road geometry and actual forecast
segment lines. It preserves disconnected route parts and fits one viewport to
the route. Forecast lines may represent nearby side roads or opposite
carriageways selected by the existing corridor intersection. They are not
assumed to correspond exactly to the chosen carriageway. There is no inferred
coverage, custom risk score, temperature correction or conversion of source
categories into safety claims.

The selected route is blue. Segment colors identify `ROAD_CONDITION` categories;
the image carries a compact wrapping legend and the source forecast valid time,
explicitly in UTC. Only categories with drawable source lines intersecting the
viewport appear in the legend. Missing values, `ErrorOrNoData` and unrecognized
categories appear gray, sharing one legend key.
`NoNewPrecipitation` retains its meaning and is not renamed “dry” or “safe”.
Full, unchanged segment properties remain available through the existing action.
An empty complete snapshot shows the route and a no-segments label. Failed or
incomplete forecast refreshes make the image unavailable along with its route
sensors. Viewing an image does not request forecasts or advance their timestamp.

Projection, PNG validation and rendering run in HA's executor. The map remains
960×480 pixels; only forecast images add the dynamically sized legend footer.
There is no repeated route title or A/B explanation. Endpoint letters are centered
using their actual glyph bounds, and outlined source/map attribution sits at the
bottom right of the map. Configuration previews have no footer.

The fitted zoom is calculated from route bounds and 36-pixel padding, retaining
the existing 0–16 limits for tiny/degenerate geometry. Previously flooring this
zoom left unnecessary space. Fractional fitting resamples a single raster mosaic
from the floor tile level, so it does not request an extra zoom level or crop the
route to simulate a closer fit. Route/forecast widths scale with zoom; they are
approximate cartographic widths, not source road-width measurements.
Visible tile count is bounded (at most 20); no zoom pyramid or
off-screen prefetch is generated. Longitude wraps around the route. Polar route
geometry beyond Web Mercator's range uses a plain geographic background rather
than imposing an integration-wide geographic restriction.

The renderer uses Pillow, already required by each supported HA core version,
including its bundled font. No host fonts, native packages or browser process
are needed at runtime. Renderer-specific labels are in `map_labels.json` because
they are drawn into PNG pixels rather than rendered by HA's translation frontend.
They follow the system language, support English/Bokmål, and fall back to English.
The actual route/device name remains available in HA's interface.

## Provider, privacy and failure behavior

Tile requests follow the [OSMF raster tile policy](https://operations.osmfoundation.org/policies/tiles/):
identified User-Agent with project/contact URL, HTTPS, visible attribution and
copyright link, a seven-day tile lifetime, bounded 16 MiB in-memory LRU cache,
four concurrent requests at most, and no prefetch or offline-download facility.
The cache is shared between flows and routes for the HA process lifetime.
It survives integration reloads and is discarded when HA stops. Eviction can
occur before seven days if the memory limit is reached.

Only requesting the preview/image causes tile retrieval. Requests contain tile
coordinates, not route names or complete route geometry. The OSM service sees
the requesting HA server's address and tile area. See the provider's
[privacy policy](https://osmfoundation.org/wiki/Privacy_Policy).
Tiles and generated private route images are not written to disk or recorder.

Requests have time and byte limits, redirects are rejected, and decoded tiles
must be 256×256 PNGs. Failures pause tile requests for at least a minute and honor
longer `Retry-After` values. Previously cached tiles can still be used during an
outage. Missing tiles produce a labeled plain background; line geometry and
source forecasts remain usable. A failed background is eligible for retry after
one minute when the image is requested again. There is no tile polling timer.
Tile failures and rate limits do not change forecast/weather/camera coordinators.

The selected OSM raster service is fixed for this beta. A future provider option
can be added if justified; no private HA map cache APIs are used for that purpose.
Images remain static; the optional [dashboard card](route-card.md) provides
interactive panning and segment popups.

## Reproduce validation

```bash
scripts/setup
scripts/check
scripts/check-minimum
scripts/check-beta
scripts/validate-hassfest
scripts/validate-hacs
scripts/smoke-ui
scripts/smoke-ui --minimum
scripts/smoke-ui --beta --rollback
git diff --check
```

Run scripts sequentially: optional dependency groups share the primary `.venv`.
The beta target has its own locked environment, CPython 3.14.8,
HA 2026.10.0b0 and pytest-homeassistant-custom-component 0.13.368. Checks CI runs
all three suites; Validate runs packaging and remote HACS checks. Both workflows
also run on `feature/**` pushes so a prerelease can be tied to a green feature
commit without merging to `main`.

The 354 mocked tests include signed-URL authentication and expiry, revocation
during rendering, preview cleanup, source colors, unchanged unusual values,
disconnected geometry, antimeridian/polar/zero-length routes, cache coalescing
and limits, tile failures/recovery, native image identities in both languages,
availability, empty forecasts and unloading. Renderer tests also cover exact
fractional fitting, tile/route alignment, zoom-dependent stroke widths, centered
marker ink, viewport-filtered legends and absent/unprojectable source geometry.
Statement coverage is 97%.

The packaged browser scenario checks the actual Markdown images in English and
Bokmål flows, a 390-pixel mobile viewport, and a PNG loaded through the native
image proxy and more-info dialog. Test routes use public town-centre coordinates.
Images and logs stay in ignored `.tools/smoke-results*` directories.

The 0.8.0b4 packaged image/preview checks passed on HA 2026.10.0b0 and the
2025.12.0 minimum. The live single-condition example rendered at 960×514 pixels,
including its 34-pixel footer; the preview is 960×480. The full map area remains
480 pixels high. Footer height increases only when its items need another row.

`--beta` runs a disposable loopback HA on port 18126. `--rollback` additionally
stops that instance, installs the exact stable 0.7.4 component from Git commit
`10658a404a4aac1b7a6808e4e9ece02bea2a809e`, restarts, and compares the 12 preexisting
entity identities, four subentries and saved configuration/route geometry. It
needs that commit in the local Git history. Only the runner's own temporary
component is replaced; HA storage is read for comparison and never edited.

The isolated beta can log an upstream `probatio.codecs` lazy-import blocking
warning from HA's `config` integration. The minimal test instance also lacks
recorder and integration diagnostics handlers. These known harness/upstream
messages are distinct from integration failures; no workaround is applied to HA.
Companion-app cache persistence and physical touch-device interaction still need
user testing. This scenario tests runtime rollback; it does not rerun interactive
HACS authorization or claim a new HACS install/upgrade lifecycle result.

Initial 0.8.0b1 validation completed on 2026-10-04: 342 tests passed on each of the three
locked targets, with 96% statement coverage. Ruff lint/format, Hassfest (zero
invalid integrations) and local HACS validation passed. Packaged browser tests
passed on all three HA versions. The beta rollback preserved all 12 existing
entities, four subentries and the saved configuration, including route geometry.
All temporary instances stopped and their configuration/authentication storage
was removed. The separate GitHub Checks and Validate workflows must pass on the
exact release commit before the prerelease is published.
