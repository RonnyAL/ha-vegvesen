# Route configuration previews

Route maps in **0.8.0** include a static preview during configuration. Saved-route
images were removed in **0.8.0b5**; the [interactive card](route-card.md) uses
cached forecasts independently of entity images.

## Native configuration flow

The route overview uses HA's supported Markdown image rendering and signed HTTP
paths. The native location selector sets endpoints; it does not expose a public
route-overlay API. HA 2026.10's vector map change does not provide such an API.
Preview URLs are signed for 30 minutes and scoped to a live flow revision.
Changing the proposal, saving or cancelling revokes its previous preview.
Concurrent viewers share one in-memory render; revocation is checked again after
rendering. Private route geometry and images are never written to public assets.

## Rendering

`route_map.py` draws the road geometry with A/B endpoint markers into a 960×480
PNG. It preserves disconnected parts, fits the actual route with 36-pixel padding
and retains fractional zoom. Line widths scale with zoom; the endpoint letters
are centered using their actual ink bounds. Attribution appears inside the map.
There is no repeated route title, condition legend or forecast overlay.
The preview confirms the proposed road route; dashboard forecasts belong to the
interactive card and route sensors.

The renderer fetches only visible OSM raster tiles at a single integer zoom,
then scales a stitched mosaic to the fitted view. Longitude wraps around the
route; polar routes outside Mercator use a plain geographic background. Rendering
and projection run in HA's executor. A basemap failure keeps the route visible
with a translated message; it does not affect source polling.

## Provider and cache

OSM [raster tile policy](https://operations.osmfoundation.org/policies/tiles/)
requires attribution, identification and caching. Requests use the integration's
User-Agent. The bounded shared memory cache retains tiles for up to seven days,
coalesces concurrent requests, respects failures and uses no bulk/offline
prefetch. It is shared across configuration previews. The renderer requests no
forecast data. OSM receives the HA server's address and requested tile areas,
not zone names or complete route geometry. The interactive card uses its own
browser-side vector provider and HTTP cache.

## Validation

Mocked tests cover PNG rendering, disconnected/antimeridian/polar geometry,
fractional fit and tile alignment, stroke scaling, centered markers, tile cache
coalescing/failure recovery, signed-path authentication and revocation during an
in-flight render. Flow tests cover cancellation, reconfiguration and saved route
identity. `scripts/smoke-ui --beta` checks the preview through the native frontend;
`--minimum` selects the minimum supported frontend. Disposable instance details
are in [validation.md](validation.md).
