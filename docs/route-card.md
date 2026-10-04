# Interactive route-map card

The **0.8.0b4** experiment remains on `feature/route-maps`. It adds an optional
dashboard card to the static previews/images introduced in 0.8.0b1. Existing
route settings, subentry versions, sensor identities and image identities are
unchanged. Installation instructions are in the [README](../README.md#interactive-dashboard-card).

## Entity and data model

One `image` entity already belongs to each saved route device. The card's `entity`
setting selects that existing entity; no artificial location entity or new map
domain is introduced. The image remains a usable static overview. A native
custom-card form filters the picker to Vegvesen image entities.

The authenticated `vegvesen/route_map` WebSocket command checks HA's entity-read
policy, resolves the current entity registry entry/config subentry, and returns
the saved geometry and complete coordinator snapshot. It works with renamed
entity IDs and refuses unrelated, disabled, unloaded or unavailable routes.
Full coordinates/properties stay outside recorder/state attributes. The command
does not call Statens vegvesen or request an image render.

HA supplies state updates to the card through its documented `hass` property.
The card retrieves a snapshot when its selected image's update timestamp changes,
when first displayed, or when the connection recovers. Changes to unrelated
entities do not request another snapshot. Responses from an older request cannot
overwrite a later failure, route change or disconnected card. Unavailable routes
clear the overlays. An explicit Retry button retries the HA request, without
triggering source polling. The integration's coordinators retain their normal
schedule. Multiple cards can request the same cached snapshot independently.

## Rendering and provider

The card bundles **MapLibre GL JS 6.12.0** and uses styles generated offline with
**VersaTiles Style 6.1.1**, in muted light/dark palettes. This follows HA's 2026.10
vector-map approach, while avoiding its internal components, token handling and
tile proxy. The unchanged minimum HA **2025.12.0** already provides the required
image, WebSocket, static-path and dashboard APIs. Browser WebGL 2 is required.

The default source is the public OSM Shortbread TileJSON at
<https://vector.openstreetmap.org/shortbread_v1/tilejson.json>. Label fonts also
come from OSM. HTTP caches retain provider cache headers; requests use the
browser's identity/referrer and omit credentials. Nothing prefetches tiles for
offline use, uploads private route geometry, or places private data in the public
JavaScript resource. The provider sees the viewer's address, HA origin and tile
areas. Users may choose another provider via the optional `map_style_url`; its
own style supplies attribution. The default always displays OSM attribution.

Source forecast lines use the same category colors as the static image. Unknown
codes, source errors and missing conditions remain gray. Since 0.8.0b3, native
MapLibre zoom expressions scale line widths roughly with the default style's
main roads, instead of keeping a fixed pixel width. Forecasts do not provide
a verified physical width or shared OSM road identifier, so neither exact
alignment nor exact width matching is promised, including with custom styles.
A transparent, at least 20-pixel line makes thin segments easier to tap; a direct
hit on a painted segment takes priority over another segment's touch area.
The A/B markers use centered letters inside 24-pixel circles. Popups render source
values as text and preserve zero, null and unusual readings. String feature IDs
are explicitly promoted through GeoJSON properties so vector-tile conversion
does not discard them. Disconnected geometry stays disconnected; longitude
wrapping only changes its display representation. A basemap failure leaves
route/forecast geometry usable and shows a message. The configuration preview
continues to use the existing simple static route image.

## Supported extension points

- [HA custom cards and graphical editors](https://developers.home-assistant.io/docs/frontend/custom-ui/custom-card/)
- [Dashboard resource registration](https://developers.home-assistant.io/docs/frontend/custom-ui/registering-resources/)
- [Extending HA's WebSocket API](https://developers.home-assistant.io/docs/frontend/extending/websocket-api/)
- [Asynchronous static paths](https://developers.home-assistant.io/blog/2024/06/18/async_register_static_paths/)
- [MapLibre API](https://maplibre.org/maplibre-gl-js/docs/)
- [OSM vector-tile policy](https://operations.osmfoundation.org/policies/vector/)

The user registers one normal JavaScript module resource. The integration does
not edit Lovelace storage, inject hidden modules or change HA's entity dialogs.
HACS's own [plugin installation lifecycle](https://github.com/hacs/integration/blob/2.0.5/custom_components/hacs/repositories/plugin.py)
adds and updates resources in storage mode and removes them on uninstall.
YAML-managed resources remain manual. An Integration download does not perform
that Dashboard lifecycle just because it contains JavaScript. This beta has
not yet been split into a separate Dashboard package; its resource registration
remains manual. This keeps resource management with HACS rather than duplicating
its use of HA's internal resource collection in the integration.
Source/tool versions are pinned in `package-lock.json`; generated assets and
third-party licenses ship in the integration folder. Development and validation
commands are in [development.md](development.md#interactive-card).

## One source repository and first-time installation

Both integration and card sources can remain in this repository. HACS's
[repository registry](https://github.com/hacs/integration/blob/main/custom_components/hacs/base.py)
keys packages by GitHub repository ID and full name, with one category per
repository. It does not support installing the same repository twice as both
an Integration and a Dashboard package. Adding a `dist/` directory alone would
not give this Integration download the Dashboard resource lifecycle.

There is another native path for a bundled card: HA's public
[`add_extra_js_url` / `remove_extra_js_url` helpers](https://github.com/home-assistant/core/blob/2026.9.4/homeassistant/components/frontend/__init__.py#L417)
explicitly support custom integrations. They exist on all three locked HA targets;
[HACS itself uses the registration helper](https://github.com/hacs/integration/blob/2.0.5/custom_components/hacs/frontend.py#L45)
for its icon module. Using that API would load the module through the integration,
without editing Lovelace storage or requiring a second HACS package. A separate
Dashboard repository is therefore an option, not a prerequisite for automation.

Before enabling that path for this card, test cold browser loads, the card picker,
normal and panel views, lifecycle and migration from manually registered resources.
There is an [upstream report of custom-module loading-order failures](https://github.com/home-assistant/frontend/issues/52570),
including panel views; that report is a reason to test our supported frontends,
not a verified failure of this card. Do not patch HA's frontend to work around it.
The intended first-time flow, once verified, would be: install the integration,
restart HA, configure a route, refresh the frontend, then add the custom card and
select the route's existing image entity. No manual resource entry would be needed.
This helper-based loading is not implemented in 0.8.0b4.

With the current bundled distribution, a new user installs the integration in
HACS, restarts HA, adds Statens vegvesen and configures a route. The native image
works immediately. To use the optional interactive card, they register the
bundled module once in Dashboard Resources, refresh the frontend, then add a
Statens vegvesen route map card and select that route's image entity. Additional
routes only need additional cards; there is no repeated resource registration.

If automatic HACS resource management is chosen later, the maintained source
can still stay here, with built card/worker/license files published to a separate
Dashboard repository. A new user would download the integration and that card
package in HACS; HACS manages the resource, and the user adds a card selecting
their saved route. YAML-managed resources remain manual. This is a distribution
option, not yet implemented; no second repository or publishing pipeline is
created for this beta.

## Validation

The mocked suite contains **354 Python tests** and passes on HA **2025.12.0**,
**2026.9.4** and **2026.10.0b0**, with 97% statement coverage. Six JavaScript tests
exercise state-driven updates, disconnect/recovery, late responses, configuration,
source categories, disconnected geometry and large/antimeridian route fitting.
ESLint, Prettier and the deterministic bundle check use the same commands in CI.

The packaged browser scenario checks actual mobile-width vector rendering,
touch panning, zoom, route fitting, source segment popups (including taps just
outside a thin painted line), English/Bokmål labels
and HA's native visual card editor; it passed on all three locked HA targets.
Street-level screenshots at zoom 16 and 18 supplement the fitted overview.
HA 2025.12's promoted edit button has a
tooltip without an accessible label; the test locates that rendered button by
its tooltip. Its native language-change view transition can report a skipped
transition. That exact browser notice is recorded; other uncaught errors fail
the test. No compatibility patch is applied to HA or its frontend.

The isolated instance uses a temporary recorder database so standard dashboard
metadata requests behave normally. The instance and database are removed after
the test. Browser screenshots/results are ignored under `.tools/card-results-*`.
Physical mobile devices and companion apps still need beta testing.
