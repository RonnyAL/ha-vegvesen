# Interactive route-map card

The interactive card ships with the **0.8.0** stable release. Installation and upgrade instructions are in the
[README](../README.md#interactive-dashboard-card).

## Route selection and data model

The graphical editor offers **Route / Rute**, a native device selector filtered
by manufacturer `Statens vegvesen` and model `Route forecast`. It lists saved route names,
excluding weather stations and cameras. The card stores `device_id`; the backend
resolves it using registry identifiers and route subentries, never display names
or model strings. A single route is preselected for a new card; several routes
require a choice. No extra entity, route catalogue or source request is needed.

The same native form exposes an optional `title` and an **Appearance** expander
containing `map_style`, `theme_mode`, `height`, `default_mode` and
`legend_expanded`, with English and Bokmål labels. Cleared optional fields return
to defaults; advanced YAML such as `map_style_url` is retained. Presentation
changes do not change route settings or request new source data.

The editor uses HA's documented `getConfigElement`, `setConfig`, `hass` and
`config-changed` lifecycle with a native `ha-form` and device selector. Existing
`entity:` cards remain supported. Their registered sensor's device is preselected
in the editor; selecting a route emits a normal config change containing
`device_id` and removes `entity`. Opening the editor does not rewrite storage.
The old experimental image
entities are retired through HA's entity registry on successful entry setup.
Saved route/subentry identities and the existing six sensor identities remain
unchanged. Existing cards selecting images require a one-time route selection.

`vegvesen/route_map` reads the current cached snapshot.
`vegvesen/subscribe_route_map` sends an initial snapshot followed by coordinator
updates, including failure/recovery and changes that leave sensor summaries
unchanged. Both accept either `device_id` or legacy `entity_id`, and perform no
source I/O. HA permissions are entity based: device selection requires read
access to at least one registered sensor belonging to that exact route. Disabled
sensors retain their permission identity, so disabling individual sensors does
not break device-based cards. Legacy selection still requires access to its
specific, enabled sensor. Access and registry identities are rechecked on each
event. Disabled/removed route devices and unloaded entries clear the map data.
An unknown summary still allows access to the route and available source data.

Subscriptions rebind to replacement coordinators on entry reload, clear overlays
on failure/unload, and remove coordinator, registry and entry listeners when
unsubscribed or disconnected. Frontend generation checks discard late callbacks
and unsubscribe late acknowledgements after card removal. Reconnection restores
the subscription. Full coordinates/properties stay outside recorder/state.

The layers panel displays category counts and explicit missing/unrecognized
counts. Route summary sensors expose highest source slipperiness separately.
Category buttons select and fit matching source geometry. A mode switch colours
by `ROAD_CONDITION` or `SLIP_RISK`; unknown codes
are gray and retain their raw labels. No arbitrary severity ordering is assigned
to road conditions. Counts describe corridor matches, not route length or exact
carriageway coverage. Filters preserve the full route as subdued context.

## Rendering and provider

### Automatic cameras and weather stations

From 0.10.0 the editor's **Road cameras** and **Weather stations** expanders expose
`show_cameras` and `show_weather` (both default false), plus `camera_distance_m`
and `weather_distance_m` (default 250, allowed 1–2,000 metres). Visibility stays
in card configuration. These are integration UI limits, not provider constraints.
Discovery is independent of forecast health, categories, corridor and map zoom.

The authenticated `vegvesen/subscribe_route_sources` command accepts the same
route target and access checks as forecast subscriptions. It rebinds on entry
reload and drops listeners on disconnect, layer changes or card removal. Two
entry-scoped `DataUpdateCoordinator`s read shared complete catalogues only while
subscribers need them: weather every ten minutes, cameras every fifteen. The
catalogue cache is also used by config flows. It coalesces concurrent requests,
caches successful empty results, and never replaces a snapshot with partial
pages. Configuration can explicitly retry an empty source list. Small expiry
slack accommodates HA's sub-second scheduling jitter without skipping a poll.
Failures clear only the affected family, and subsequent healthy updates recover
it. The saved geometry remains available when forecasts fail.

On 2026-10-06 the public OGC catalogue contained 468 stations and 896 cameras.
Full catalogue snapshots use the existing limit-500 pagination, bounded by the
client's total 30-second deadline. Live bbox queries also worked for both
collections. A shared full snapshot avoids one discovery request per route and
keeps overlapping routes consistent; only matching records go to each browser.
If catalogue sizes grow substantially, review this tradeoff. No numerical quota
or atomic server snapshot guarantee was verified.

Matching uses the existing Shapely/pyproj route corridor in HA's executor,
including each disconnected part separately. It compares source point positions
to the saved route, rather than to forecast segments. Invalid/missing coordinates
cannot be drawn; measurements are never screened or corrected. The browser no
longer needs Turf or a second proximity algorithm. Cameras retain their direction
suffixes and weather/camera namespaces stay distinct. Faulted cameras remain
visible with their source status; weather nulls remain missing and zero/unusual
values are retained. Observation times are source times, displayed in HA's time
zone; temperature display respects the configured Celsius/Fahrenheit unit.

Choosing a camera calls `vegvesen/route_camera`, following HA's documented
[authenticated thumbnail pattern](https://developers.home-assistant.io/docs/frontend/extending/websocket-api/).
The server verifies route access and camera proximity before I/O and route
identity/access again after I/O. Image URLs are never supplied by the browser or
exposed in map metadata. Manually configured cameras reuse a recent coordinator
snapshot. If entity polling is disabled and the snapshot has expired, map viewers
use the on-demand cache instead. Others refresh selected metadata and JPEGs on demand, coalescing
concurrent viewers and caching success/failure for 60 seconds. Four concurrent
requests and a 16-frame memory cache bound demand. JPEG transport is capped at
5 MiB per image; existing endpoint restrictions, redirect rejection, source
availability checks and Retry-After handling apply. Closing an image cancels its
frontend timer and rejects late results; no discovered image is polled in the
background. No capture timestamp is inferred.

Source markers within 40 screen pixels form collapsed groups. A tap opens a
compact list without changing the camera; mixed camera/weather groups use the
same mechanism. A second tap chooses a source. Groups return after details close,
then collapse after eight idle seconds unless hovered or focused. Escape, map
movement and closing dismiss them. Zoom separates nearby positions, while exact
coincidences remain grouped. Controls use public MapLibre markers/popups/events,
not HA internal components. The design follows HA 2026.10.0b0's
[`ha-map`](https://github.com/home-assistant/frontend/blob/20260930.0/src/components/map/ha-map.ts)
and [MapLibre engine](https://github.com/home-assistant/frontend/blob/20260930.0/src/common/map/engines/maplibre-map-engine.ts).

Discovery creates no subentries, devices, entities or recorder states. Manual
sources keep their existing ownership and identity. Overlapping routes reference
the same source IDs and caches; removing a card does not remove a manual source.
Area monitors and automatic physical-entity ownership remain future work.

Python tests mock the network boundary to cover atomic pagination, sharing,
independent failures, empty catalogues, recovery, access, unloading, proximity
and on-demand images. Browser smoke checks first exercise real public discovery
on the disposable route, then inject clearly synthetic source events/image
responses to test deterministic grouped-camera/weather interactions and failure
states. No synthetic state is deployed to an existing HA installation.

### Vector map

The card bundles **MapLibre GL JS 6.12.0** and uses styles generated offline with
**VersaTiles Style 6.1.1**, with six light/dark style pairs. This follows HA's 2026.10
vector-map approach, while avoiding its internal components, token handling and
tile proxy. The unchanged minimum HA **2025.12.0** already provides the required
WebSocket, static-path and dashboard APIs. Browser WebGL 2 is required.

The reference is **HA Core 2026.10.0b0**, whose
[frontend manifest](https://github.com/home-assistant/core/blob/2026.10.0b0/homeassistant/components/frontend/manifest.json)
pins **frontend 20260930.0**. Its
[map-card editor](https://github.com/home-assistant/frontend/blob/20260930.0/src/panels/lovelace/editor/config-elements/hui-map-card-editor.ts)
groups visual settings under Appearance, and its
[style definitions](https://github.com/home-assistant/frontend/blob/20260930.0/src/common/map/map-styles.ts)
offer Default, Colorful, Natural, Muted, Gray and Toner. This card uses those
preset names and Auto/Light/Dark theme semantics, with no automatic title.

The default light/dark color tables are copied from HA's Apache-2.0
[`ha-map-palette.ts`](https://github.com/home-assistant/frontend/blob/20260930.0/src/common/map/ha-map-palette.ts),
with source attribution and its license in the source tree and bundled notices.
The remaining palettes come from the pinned VersaTiles builder. The build emits
twelve local JSON assets; only the selected style is fetched, using the module's
version parameter. No runtime builder, HA-internal style imports or map proxy
is required. Source condition colors retain their meaning across all styles.

Auto follows `hass.themes.darkMode`. Forced modes change map controls and panels
along with the basemap, even when the HA page uses the opposite mode.
Style changes use MapLibre's public `setStyle` and `style.load` lifecycle,
restoring forecast layers from the current snapshot while keeping the map camera
and selected source. This does not implement HA's advanced per-feature map
color overrides or arbitrary custom `map_style` objects. Existing
`map_style_url` configurations take precedence over presets; Theme mode changes
their UI but does not recolor an external provider's style.

The default source is the public OSM Shortbread TileJSON at
<https://vector.openstreetmap.org/shortbread_v1/tilejson.json>. Label fonts also
come from OSM. HTTP caches retain provider cache headers; requests use the
browser's identity/referrer and omit credentials. Nothing prefetches tiles for
offline use, uploads private route geometry, or places private data in the public
JavaScript resource. The provider sees the viewer's address, HA origin and tile
areas. Users may choose another provider via the optional `map_style_url`; its
own style supplies attribution. The default provides OSM attribution through
MapLibre's public attribution control. From 0.8.0 this follows HA's
[`attributionControl: {}`](https://github.com/home-assistant/frontend/blob/20260930.0/src/common/map/engines/maplibre-map-engine.ts)
configuration: inline above 640 pixels; collapsible and initially open on narrower
maps, minimizing on drag. The library handles resizing and keyboard interaction.
Its light credit (translucent when inline) and 12-pixel type match HA's native
vector map, including in dark mode. The copyright text stays dark for contrast and the
information button has English/Bokmål labels. In-map panels reserve room for it.

Source forecast lines can be coloured by road condition or source slipperiness. Unknown
codes, source errors and missing conditions remain gray. Since 0.8.0b3, native
MapLibre zoom expressions scale line widths roughly with the default style's
main roads, instead of keeping a fixed pixel width. Forecasts do not provide
a verified physical width or shared OSM road identifier, so neither exact
alignment nor exact width matching is promised, including with custom styles.
A transparent, at least 20-pixel line makes thin segments easier to tap; a direct
hit on a painted segment takes priority over another segment's touch area.
The A/B markers use centered letters inside 24-pixel circles. The segment panel
renders source values as text and preserves zero, null and unusual readings.
Feature IDs are explicitly promoted through GeoJSON properties so vector-tile conversion
does not discard them. Disconnected geometry stays disconnected; longitude
wrapping only changes its display representation. A basemap failure leaves
route/forecast geometry usable and shows a message. The configuration preview
continues to use the existing simple static route image.

Since 0.8.0b8, tapping a segment selects its stable source ID, draws an outline
without changing its condition colour, and shows its details. A new
snapshot refreshes those details without changing the viewport. Missing records,
missing geometry, failures and disconnects clear the selection; choosing a
category or fitting the route also resets it. Data-quality counts sit in an
expandable section inside the layers panel.

From 0.8.0b9, zoom, fit, expansion and layers controls occupy a compact column
inside the map on the left. The legend starts collapsed; its popup and the
segment panel stay inside the map, leaving attribution and controls accessible.
The panels alternate so they do not overlap each other. An explicit
`legend_expanded: true` retains the open-on-start preference. The card's height
stays fixed while inspecting a source, with scrolling inside long panels.

Expansion uses MapLibre's public `FullscreenControl` with the whole card as its
container. Its built-in CSS fallback supports browsers without the Fullscreen
API. The map fills the remaining height, with the legend and segment details
available in the same view. Controls have translated labels, and card teardown
releases its expanded container. No HA dialogs, private frontend hooks or map
components are used for expansion. Companion WebView behavior still needs
physical-device testing.

Fit bounds leave a margin for the left control column.

From 0.8.1, map controls follow the
[native map card's buttons](https://github.com/home-assistant/frontend/blob/20260930.0/src/panels/lovelace/cards/hui-map-card.ts):
MapLibre's boxed 29-pixel zoom controls sit above transparent action buttons with
48-pixel touch targets and 24-pixel icons. Actions use black in light map mode and
white in dark map mode, with a subtle circular hover state. Zoom uses MapLibre's
white surface or HA's fixed `#1c1c1c` dark surface; dashboard card backgrounds no
longer recolor it. Fit uses HA's reset-focus icon. The existing HTML buttons retain
their labels, keyboard activation and expanded-state semantics, and MapLibre's
public fullscreen control retains its lifecycle and CSS fallback. This is CSS
styling of the existing controls; the card does not import or patch HA's internal
map components.

## Layer switching and panels

From 0.8.3, the closed layers panel leaves no summary overlay on the map.
The layers control opens forecast time, category counts and missing-data
details on demand. Forecast updates do not reopen a closed panel, and
`legend_expanded: true` still opens it initially. Unavailable/error messages
remain visible; browsers without WebGL retain the textual fallback panel.

From 0.8.2, switching between Road condition and Slipperiness preserves the
map's position, zoom, bearing and pitch. A category filter belongs to its layer
and is cleared when changing layers; pressing the already active layer keeps
the filter. Category selection and Fit route remain explicit fit actions.

The in-map panels use a grouped layer selector, list rows with aligned category
counts, 44-pixel button targets and readable label/value rows for segment
details. Both panels have labeled close buttons; closing the layer panel
returns keyboard focus to its map control. Missing-data details remain
expandable, with each count on its own line. Panels stay inside the fixed map
height, scroll when necessary, and retain light/dark theme behavior.

These presentation choices follow the grouping and selected-state treatment in
HA's [control selector](https://github.com/home-assistant/frontend/blob/20260930.0/src/components/ha-control-select.ts),
using ordinary HTML controls and existing theme variables. HA's
[custom-component guidance](https://developers.home-assistant.io/blog/2026/03/25/frontend-component-updates-2026.4/)
does not promise stable internal frontend component APIs; the card does not
import the selector or add an internal dialog dependency.

## Supported extension points

- [HA custom cards and graphical editors](https://developers.home-assistant.io/docs/frontend/custom-ui/custom-card/)
- [Native device selector filters](https://www.home-assistant.io/docs/blueprint/selectors/#device-selector)
- [Dashboard resource registration](https://developers.home-assistant.io/docs/frontend/custom-ui/registering-resources/)
- [Extending HA's WebSocket API](https://developers.home-assistant.io/docs/frontend/extending/websocket-api/)
- [Asynchronous static paths](https://developers.home-assistant.io/blog/2024/06/18/async_register_static_paths/)
- [MapLibre API](https://maplibre.org/maplibre-gl-js/docs/)
- [OSM vector-tile policy](https://operations.osmfoundation.org/policies/vector/)

## Bundled loading and lifecycle

Starting with 0.8.0b7, the integration registers its bundled module through HA's
public [`add_extra_js_url` / `remove_extra_js_url` helpers](https://github.com/home-assistant/core/blob/2026.9.4/homeassistant/components/frontend/__init__.py#L417).
These helpers explicitly support custom integrations and exist on all three
locked HA targets. [HACS uses the registration helper](https://github.com/hacs/integration/blob/2.0.5/custom_components/hacs/frontend.py#L45)
for its icon module. The module URL includes the loaded integration manifest's
version, so the next release supplies a new URL without a dashboard edit.

HA starts extra modules alongside its own app, whose
[entry point initializes the custom-element registry](https://github.com/home-assistant/frontend/blob/20260930.0/src/entrypoints/app.ts).
Before defining the editor and card, the module waits for the `home-assistant`
root component using the browser's standard
[`customElements.whenDefined`](https://developer.mozilla.org/en-US/docs/Web/API/CustomElementRegistry/whenDefined).
This prevents an early registration from being lost during HA startup. It does
not replace or patch the registry. The browser scenario delays HA's app to test
this ordering, as well as repeated warm reloads.

The frontend is an optional `after_dependencies` entry. When available, module
registration happens during config-entry setup and removal uses
`entry.async_on_unload`. Failed setup, unloading, disabling and removal clean up
the registration; a successful retry/reload registers it again. Static file
serving and the WebSocket handlers remain scoped to the integration component.
A headless installation can use the weather/camera/forecast data without starting
HA's frontend. Browser code already loaded cannot be unloaded from an open page;
its data subscription still handles entry unloading and clears unavailable data.

Registered URLs are included in subsequent frontend page loads. After first
configuration or an update, users refresh the browser or reopen the companion
app. Config-entry reloads do not replace Python or JavaScript code already
loaded in memory. No hot reload, dashboard-storage mutation or cache clearing is
implemented. The existing manifest/static-path/WebSocket APIs and minimum HA
2025.12.0 remain sufficient.

A new user installs the integration, restarts HA, configures a route, refreshes
the frontend, then chooses **Add card → By card → Statens vegvesen route map** and
selects the route. No local files or manual resource registration are required.
Both the integration and card are maintained and shipped in this repository.
HACS installs the Integration package; HA's frontend helper handles module
loading. This does not depend on HACS installing the same repository twice in
different categories or on its Dashboard-package resource lifecycle.

Old manual resource entries are left under the user's control. Element and
card-picker registrations are idempotent, allowing the old URL and automatic
URL to coexist. Removing the old resource through HA's Resources UI is a
one-time cleanup; users need not maintain its version parameter. YAML resource
entries can likewise be removed from the user's own configuration. The generated
JavaScript contains no credentials or route coordinates. Map-provider requests
start only when a map is rendered, as described above.

The source/tool versions are pinned in `package-lock.json`; generated assets and
third-party licenses ship in the integration folder. Development and validation
commands are in [development.md](development.md#interactive-card).

## Validation

Run `scripts/check`, `scripts/check-minimum`, `scripts/check-beta` and
`npm run check`. Python tests cover source grades/counts, missing and unknown
codes, current-hour settings, image registry cleanup, permissions, unchanged
summaries with changed segment data, unload/reload, failure/recovery and socket
cleanup, device selection, disabled sensors, registry removal and legacy sensor
compatibility. JavaScript tests cover subscription updates, late acknowledgements,
disconnect/recovery, route changes, editor migration, default selection, source
categories and highlight bounds.

`scripts/smoke-ui --beta --route-card` exercises the packaged card in a disposable
HA, with mobile-width vector rendering, touch pan/zoom, persistent segment details,
category highlighting, native fullscreen and the library's CSS fallback. It also
checks English/Bokmål labels, the native route picker, saving a legacy card with
a device selection and retaining presentation settings after reload. Use `--minimum`
instead of `--beta` for the minimum frontend. Logs/screenshots remain ignored
under `.tools/card-results-*`; temporary HA, credentials and database are removed
on exit. Companion apps and physical mobile devices require separate manual testing.

For 0.8.0b5, all 357 Python tests passed on HA 2025.12.0, 2026.9.4 and
2026.10.0b0 (97% statement coverage), alongside seven JavaScript tests. Packaged
mobile card checks passed on the minimum and beta frontends; native preview,
0-hour default and Bokmål unit-label checks also passed on those two targets.
The isolated 0.7.4 rollback retained all 12 stable entities, four subentries and
saved configuration, including the 0-hour route setting. Beta-only sensors are
excluded from stable identity comparisons and may remain unavailable on rollback.

For 0.8.0b6, all 362 Python tests pass on the same three locked HA targets
(97% statement coverage), alongside nine JavaScript tests. Packaged card checks
on the minimum and beta frontends verify the native Route/Rute device picker,
preselection for legacy cards, normal editor saving to `device_id`, and a fresh
page load of the saved device-based card. Touch interaction, category selection
and failure handling retain their existing coverage.

For 0.8.0b7, all 364 Python tests pass on the three locked HA targets
(97% statement coverage), alongside nine JavaScript tests. New tests cover
automatic registration, failed setup/recovery, unload/removal and headless setup.
Packaged browser checks on HA 2025.12.0 and 2026.10.0b0 start without Dashboard
Resources and verify startup after an HA restart, the card picker, repeated
editor openings/reloads, cold masonry/panel/sections/YAML dashboards, coexistence
with a manual resource, deleting that resource, and disabling/re-enabling the
integration with a frontend refresh. The minimum frontend also passes the
deliberately delayed HA-app startup check. These use disposable configurations
and public route coordinates; physical companion-app testing remains necessary.

For 0.8.0b8, the 364 Python tests retain 97% statement coverage, and all 12
JavaScript tests pass. The packaged browser scenario passes on HA 2025.12.0 and
2026.10.0b0, including native fullscreen, simulated absence of the Fullscreen API,
touch selection, persistent details after refreshed values, unchanged viewports,
zero/null/unusual temperatures, disappearing segments and unavailable data.
It saves the title, height, initial layer and legend preference through native
editor controls and checks them after repeated reloads. English/Bokmål labels,
automatic registration and the existing loading/unloading checks also pass.

One minimum-frontend run reported an intermittent null-config error in HA's
[`themes-mixin`](https://github.com/home-assistant/frontend/blob/20251203.0/src/state/themes-mixin.ts)
during reload. A rerun passed without changing or suppressing that error check.
The older frontend's already documented skipped-view-transition notices remain;
the card does not patch HA's theme or transition behavior. Browser emulation is
not a substitute for checking expansion in physical companion apps.

For 0.8.0b9, all 14 JavaScript tests pass, including the six packaged style pairs,
HA palette colors, theme-mode selection and compatibility with existing settings.
The 364 Python tests retain 97% statement coverage. Packaged browser scenarios
pass on HA 2025.12.0 and 2026.10.0b0: no default title, controls on the left,
fixed card height while inspecting, every light/dark palette, automatic HA theme
changes, forced-mode UI contrast, retained viewport/selection across style changes,
native Appearance settings saved across reloads, and failed-style fallback/recovery.
Existing fullscreen, language, source-data and registration lifecycle checks also
pass. Screenshots include 390-pixel mobile width and the minimum 240-pixel map
height; physical companion-app testing remains necessary.

For stable 0.8.0, the 364 Python tests and 14 JavaScript tests remain passing.
Packaged browser checks pass on all three targets: HA 2025.12.0, 2026.9.4 and
2026.10.0b0. New checks cover the native responsive attribution: initial credits,
collapse on touch pan, click/keyboard reopening, inline credits in a wide
fullscreen view, English/Bokmål toggle labels, theme contrast and clearance
below segment details at the minimum map height. The older frontend's selector
test now blurs its closing menu through the dialog header before opening the
next dropdown; runtime selectors are unchanged. Existing expected skipped-view-
transition notices remain confined to the minimum frontend.

For 0.8.1, the packaged browser scenario passes on HA 2025.12.0 and 2026.10.0b0.
It checks native zoom dimensions/colors, transparent action surfaces, 48-pixel
targets, spacing and icon colors across all styles and Auto/Light/Dark modes,
including a custom dashboard card background. Existing interaction, fullscreen,
attribution and lifecycle checks pass. The older selector test uses native
keyboard activation to avoid overlapping Material menu animations. One run
encountered the previously documented minimum-frontend null-config error during
reload; a rerun passed without suppressing it or changing runtime code. The
364 Python tests, 14 JavaScript tests, lint/formatting and local packaging checks
also pass; no dependency versions changed.

For 0.8.2, packaged browser checks pass on HA 2025.12.0 and 2026.10.0b0.
The layer-switch regression uses the real buttons after zooming, waits for
MapLibre's zoom animation to finish, and verifies unchanged position, zoom,
bearing and pitch while the forecast colors change. It also covers clearing a
previous layer's category filter, retaining a filter when pressing the active
layer, keyboard focus, the panel close button, touch-target sizes and horizontal
overflow. Existing mobile, minimum-height, light/dark, source-value and lifecycle
checks continue to pass. The minimum frontend retains its previously documented
native view-transition notices. All 364 Python tests pass on the three locked
targets, alongside 14 JavaScript tests, lint/formatting, reproducible bundle,
Hassfest and local HACS packaging checks. No dependency versions changed.

For 0.8.3, packaged browser checks pass on HA 2025.12.0 and 2026.10.0b0.
They verify no default summary overlay, opening/closing the layers panel,
forecast updates leaving it closed, available missing-data details and the
retained expanded-legend preference. The minimum frontend's test now waits for
the Material menu's opening animation before selecting an option; two earlier
runs selected values before opening completed and left menus open. Native
selectors remain unchanged. All 364 Python tests pass on the three locked
targets, alongside 14 JavaScript tests, lint/formatting, the reproducible bundle,
Hassfest and local HACS packaging checks. No dependency versions changed.
