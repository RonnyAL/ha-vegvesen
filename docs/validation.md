# Compatibility, packaging and isolated UI validation

## Tested targets

| Purpose | Home Assistant | Python | pytest custom-component package | Lock |
| --- | --- | --- | --- | --- |
| Primary development | 2026.9.4 | 3.14.8 | 0.13.367 | `uv.lock` |
| Beta compatibility | 2026.10.0b0 | 3.14.8 | 0.13.368 | `environments/beta/uv.lock` |
| Minimum supported | 2025.12.0 | 3.13.11 | 0.13.298 | `environments/minimum/uv.lock` |

All three run the same 417 mocked tests with 97% integration statement coverage. The minimum is justified by the runtime APIs used, particularly [`UpdateFailed(retry_after=...)`](https://developers.home-assistant.io/blog/2025/11/17/retry-after-update-failed/), config subentries, source unique IDs, subentry entity/device registration, entry runtime data and coordinator lifecycle hooks. Earlier versions have not been claimed or tested. Patch Python versions here are development pins, not integration requirements imposed on an HA-managed installation.

For 0.12.4, packaged browser checks exercise a native top-layer forecast popover
on short cards, including touch selection outside the card, automatic placement
above/below, right-screen-edge shifting, resize while open and dashboard scrolling.
They also cover hiding when the clock leaves view, dismissal by a second native
popover, fullscreen, cleanup on removal and the contained compatibility fallback.
The styling remains in the card's shadow DOM. Floating UI DOM is bundled and
locked; its own license and dependency licenses are included in the package.

For 0.12.3, the packaged browser scenario checks the bottom-left forecast controls
and card-contained themed menu on minimum and beta HA. It verifies touch/outside
dismissal, keyboard navigation and focus, grouped dates and default markers,
unchanged pan/zoom and loading bounds, English/Bokmål, dark mode, 320-pixel width,
240-pixel map height, attribution clearance and fullscreen. The forecast transport
and cache remain unchanged; all 35 frontend tests still apply. Companion-app
hardware testing remains separate from Chromium touch emulation.

For 0.12.2, the 35 frontend tests include card-default validation, rolling UTC-hour
offsets, Now labels, fixed manual selections, disconnect/visibility recovery,
responses crossing hour boundaries and timer cleanup. The packaged browser
scenario checks the native grouped hour picker on the left, marked defaults,
unchanged control bounds while a response is delayed, English/Bokmål, dark mode,
320-pixel width, 240-pixel map height, touch/keyboard access and saved editor
defaults. It retains real requested-hour API checks plus deterministic empty,
failed and recovered responses. Browser touch emulation does not replace
physical companion-app testing.

For 0.12.1, the packaged browser scenario exercises the separate forecast clock,
native hourly slider and compact bottom controls on minimum and beta HA. It
checks real touch dragging without intermediate requests or map panning,
release-to-load behavior, precise arrows, one-tap Automatic, Escape/focus,
320-pixel width, 240-pixel map height, English/Bokmål and light/dark styles.
Failure messages leave the clock accessible. Live requested-hour responses,
empty/error/recovery states and the existing source and lifecycle checks remain
covered. Physical companion-app testing is separate from Chromium touch emulation.

For 0.12.0, eleven map-transport tests cover shared action caching, device/legacy
selection, complete/empty/failed forecasts, independent sensor availability,
range validation and permission/entry/subentry changes during I/O. The 29
frontend tests include selected-hour state, rapid arrow changes, queued requests,
late responses, default subscription updates, visibility, expiry, recovery and
repeated local DST hours. Compatibility and dependency pins remain unchanged.

Packaged 0.12.0 browser checks pass on minimum and beta HA. They request live
forecast hours through the selector and both sets of arrow buttons, verify
unchanged map position/zoom, return to Automatic and exercise empty, failed and
recovered responses. Screenshots and checks cover English/Bokmål, light/dark,
320-pixel width, keyboard focus and the temporary time controls. Existing source
groups, segment details, resource registration and unload/reload checks also
pass. One minimum run encountered the previously documented native HA theme
initialization error during reload; a clean rerun passed without relaxing the
error checks or changing HA behavior.

For 0.11.0, requested-hour action tests cover hour/time-zone conversion, DST
offsets, bounds, cached and concurrent queries, cancelled callers, pagination
failure, wrong hours, null/zero/unusual values, unknown source categories,
unpublished hours, cache expiry/eviction, timeout, shared rate-limit cooldown,
recovery, unloading/reloading and removal during I/O. Tests verify that explicit
queries leave sensor state, settings and polling timers unchanged. The documented
briefing runs through HA's native automation validation and script engine with
mixed, empty and failed mocked responses. The existing polling/lifecycle suite
also runs unchanged. See the [forecast action reference](forecast-action.md) for
the API investigation, cache boundaries and source availability limitations.

Packaged live checks pass on minimum and beta HA: a +2-hour action response for
the public Trondheim–Orkanger route, an identical cached repeat, compact output
and unchanged map data, followed by the existing mobile/card lifecycle scenario.
The browser runner waits for the map's actual resize event before checking popup
focus after changing card height; this removes a race in the test without changing
runtime behavior.

The [public release review and 0.7.4 follow-up](release-readiness.md) record the code,
documentation and package assessment. Six additional action-error tests exercise
native exception translation for missing/wrong devices and unloaded routes in
English and Bokmål. All translation keys and placeholders match across languages.

The 0.9.0 route regressions cover bounded timeout, unexpected calculation failure,
retry, retained drafts and cancellation through HA's native flow manager, plus
one-metre corridor matching. Camera tests verify source coordinates, null/zero
positions and independent cached-image failure/recovery. The frontend suite has
20 tests, including geodesic camera matching, disconnected route parts, source
identity and native proxy selection. Packaged-card browser runs on minimum and
beta HA cover camera markers, direction selection, failed image requests,
recovery/removal and native editor saving at mobile and desktop sizes. Camera UI
fixtures are synthetic; backend tests use mocked public source responses.

For 0.9.1, the frontend suite has 24 tests, including stable grouping of coincident
and nearby points, regrouping at closer zoom, bridging groups and distinct source
types. Packaged-card checks on minimum and beta HA exercise collapsed counts,
keyboard/touch selection, focus retention, eight-second idle collapse, rapid taps
without map zoom, larger scrollable groups in dark mode and cleanup when hidden
or removed. Source visibility remains available through the native card editor;
there is no source toggle or count row in the map's forecast panel.

For 0.10.0, automatic discovery adds mocked network tests for shared catalogue
requests, complete pagination, empty results, route proximity, independent feed
failures, Retry-After, permission changes, reload/unload and on-demand image
sharing. The 22 frontend tests replace browser-side proximity tests with source
payload, setting-change, unit/null/zero and late-event tests; proximity is now
covered in Python. Packaged-card checks use live public discovery without manual
source entities, then synthetic camera/weather events for deterministic mixed
groups, observation details, failure recovery and native editor persistence.
The compatibility floor stays HA 2025.12.0: the new transport uses its supported
WebSocket extension API and existing config-entry/coordinator lifecycle hooks.

For 0.10.1, the 23 frontend tests include mixed-group sections, direction labels,
same-name source disambiguation and unchanged source records. Packaged browser
checks pass on HA 2025.12.0 and 2026.10.0b0: both icons in collapsed mixed markers,
weather-first lists, full-width touch targets, camera directions, focus restoration,
unchanged map view and weather access after camera removal. The three-source
list fits the normal card height without scrolling. The minimum frontend also
checks scrolling at the minimum 240-pixel height; both exercise 320-pixel width,
Bokmål and dark mode. Its existing native view-transition notices remain scoped
to the older frontend; no runtime workarounds or broader error exclusions were
introduced. The [grouping investigation](source-grouping.md) records actual
co-location counts and official design references.

The 0.7.4 regression verifies that weather refreshes update only devices owned
by their config entry. Recovery tests also check that device-name updates emit
no deprecated lookup warning while preserving user names and existing entity IDs.
Both target suites and local lint, formatting, Hassfest and HACS checks passed.

The [0.7.2 runtime review](runtime-review.md) adds regressions for initial HTTP 429
with and without a healthy source family, automatic retry, manual refresh,
entry reload, discovery, later-page failures and image cooldowns. Action tests
cover registration before entries, setup retry, unloaded routes and resolution
of the new runtime after reload. Weather-name tests cover new and legacy
subentries, missing startup data, recovery, existing IDs and user device names.

The route scheduler tests advance HA’s actual timer with mocked HTTP responses. They cover hour/half-hour boundaries, midnight and the UTC hour of Oslo’s daylight-saving transition, manual refresh alignment, a request crossing an hour, unchanged states, failure/recovery, Retry-After spanning a boundary, disabled polling and unloading. These tests use virtual time and isolated HA fixtures.

The [0.6.3 config-flow review](config-flow-review.md) records native API choices and fixes. New mocked tests cover pending-flow cancellation, progress revisits, cleared optional selectors, numeric validation and translated progress/errors on both supported targets.

The [0.6.4 API constraint review](route-forecasts.md#api-constraint-review--064)
distinguishes documented request requirements, observed forecast availability
and integration UI limits. Additional tests cover documented/live routing error
formats, correcting off-network map/zone endpoints in parent/subentry flows,
retained drafts and successful retry, and an unpublished forecast without fallback.

The 0.7.0 source-flow tests cover the three native forms, multiple checkbox
selections, empty selections and cached restarts in all four parent/subentry
paths. Geography tests require the official Norwegian municipality name and
check every bundled label against Kartverket's directory fixture.

The 0.7.1 presentation tests load `icons.json` through HA's native icon helper.
Route tests cover automatic names with zero, one or two zones in both parent
and subentry flows, custom overrides, cleared names, translated entity IDs and
preservation of user-assigned entity IDs, names and icons across a route rename.
Temperature and timestamp sensors retain their device-class icons.

The Bokmål test configures HA with language `nb`, checks translated temperature and observation names, resolves both translated subentry actions through HA's translation loader, and verifies source-based entity identity remains intact.

The minimum's aiodns 3.5.0 cannot import with pycares 5, so its environment explicitly pins pycares 4.11.0. The matching test package pins HA 2025.12.0. Its lru-dict 1.3.0 has no CPython 3.13 wheel; a Zig 0.15.2 compiler builds it locally. The wrapper omits CPython's `--exclude-libs,ALL` linker flag, which Zig cannot parse and which is unnecessary for this extension without linked static archives. Other arguments are preserved.

Optional frontend dependencies require two further native builds on Python 3.14. Their isolated build environments use the same pinned Zig compiler. Setuptools, wheel and pybind11 build dependencies are constrained explicitly. All compilers, managed Python 3.13, environments, downloaded source archives, native libraries and caches remain inside ignored repository directories. System Python and packages are unchanged.

## Reproduce the checks

Use uv 0.12.22. Native source selection requires no integration JavaScript or Node toolchain. These scripts fall back to `$HOME/.local/bin/uv` when necessary; `VEGVESEN_UV` can override it.

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
# Interactive: requires GitHub's normal HACS device authorization.
scripts/smoke-ui --hacs
git diff --check
```

Setup and the five deterministic checks match CI. Run environment-syncing scripts sequentially. The live UI smoke test is an explicit local check for Debian 12 amd64, separate from deterministic mocked tests. Normal setup, test and packaging scripts never start HA or use Docker. Optional dependency groups share the primary `.venv`; `uv sync` installs the selected groups and removes unselected ones. Run `scripts/smoke-ui` again to restore the browser/frontend group after ordinary setup or validation.

## Packaging validation

`scripts/validate-hassfest` runs all Hassfest validators from official [HA 2026.9.4 source](https://github.com/home-assistant/core/tree/2026.9.4/script/hassfest), using a SHA256-checked source archive. Result: one integration, zero invalid integrations, no warnings. This exposed and corrected missing `entry_type` and `initiate_flow.user` subentry translations and removed obsolete title keys.

`scripts/validate-hacs` imports [official HACS 2.0.5 manifest schemas](https://github.com/hacs/integration/blob/2.0.5/custom_components/hacs/utils/validate.py) without loading HACS's startup code. It validates both manifests, the single-domain package layout, essential files and local PNG dimensions. Result: passed. The generic road/weather icons are original artwork under the project's MIT license; they are not Statens vegvesen's logo. The editable SVG accompanies 256px and 512px PNGs. Local assets follow [HA's file structure](https://developers.home-assistant.io/docs/creating_integration_file_structure/#brand-images---brand) and [HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/).

The separate remote HACS action runs for public repositories with `comment: false` and no ignored checks, including description, topics and brand assets. It inspects GitHub repository content and metadata; its results are available in the repository's Actions tab after pushing. Private repositories are skipped because HACS cannot install them. The repository has a public description and search topics; `hacs.json` declares Norway with `country: "NO"`. This is distribution metadata, not a restriction on source or route selection. Its pinned action wrapper still uses HACS's upstream `main` Docker image, so that remote check is not reproducible to the same degree as the pinned local checks. A local pass is not a claim of HACS listing or successful HACS installation.

## UI smoke test

The route-map scenario extends this with rendered preview checks and
an optional stable rollback. See [route-maps.md](route-maps.md) for the separate
HA beta target, isolation, current test coverage and limitations. Historical release
evidence below retains the versions and entity counts actually tested.

The packaged 0.7.3 check passed on both HA 2026.9.4 and HA 2025.12.0 on
2026-10-04, including native progress,
cached discovery, English/Bokmål source and route forms, zone/map endpoints,
reconfiguration and live entities. Initial weather/camera lists opened in
0.59/0.72 seconds on the primary target and 0.50/0.76 seconds on the minimum;
cached weather discovery took 0.06/0.05 seconds respectively. These are single-run
observations, not API or UI performance guarantees. The runner waits for HA's
parent reload before opening the next subentry flow, since HA disables its parent
chooser during that reload.

The runner checks port 18123 is free and starts a disposable HA 2026.9.4 instance
on `127.0.0.1`. With `--minimum`, it uses port 18124 and HA 2025.12.0 from the
separately locked Python 3.13 environment. Each target pins its own frontend and
optional HA dependencies; the primary environment runs Playwright for both.
The runner creates an ephemeral owner and confirms the primary target's loopback
HTTP settings using the same native API as HA's Confirm button. Default onboarding
integrations and analytics are skipped. Its coordinates are deliberately zero and
are unrelated to source selection. It builds a runtime-only ZIP and extracts the
custom component into the temporary configuration. The HA child runs with that
directory as its working directory and Python's `-E` option, so the repository and
an inherited development `PYTHONPATH` cannot shadow the installed package. The
package includes English/Bokmål translations, the original license and attribution.

The first-use test opens the county form and selects **Trøndelag → Orkland**,
then checks **Fv 714 Våvatnet (1629006)** and **Fv 65 Bye (1629004)** together.
It checks that an empty selection cannot save, then creates two weather subentries
with one final submission. It adds **Møre og Romsdal → Herøy → Rundebrua — Runde
(3000047_2)** using the camera checkbox form. It switches to Bokmål and checks
native field labels and checkbox selections for both families. Trøndelag's
municipality options must include **Røros**, not the priority name **Rosse**.
The Bokmål route form is also checked with a blank name, producing
**Trondheim → Orkanger**. The native more-info dialogs render the road-condition,
slipperiness and segment-count icons from the packaged `icons.json`.
No translation resources are manually injected. Screenshots and timing results
remain ignored in `.tools/smoke-results` and `.tools/smoke-results-minimum`.

The runner also saves the public Trondheim–Orkanger route through native map/coordinate inputs, checks its editable overview and proposal selector, then exercises the full Bokmål route flow: named zones, a mixed zone/map pair, all four overview labels, the route proposal label, retained choices when editing, and an existing route's reconfigure action. The result has three physical devices, one route service device and twelve entities. Six route forecast states must become available against the live API. The test checks weather
and camera states, retrieves a JPEG through HA's camera proxy, opens the camera
details dialog, and checks the rendered image. It also reopens a weather flow
to exercise cached discovery. The minimal test instance has no recorder or
integration diagnostics handler; frontend requests for `recorder/info` and
`diagnostics/get` report unsupported-command/domain errors. They do not prevent
picker, entity or image checks. The minimum frontend also reports a skipped view
transition when navigation starts another transition. These checks use fresh
browsers on both targets; they do not cover an open companion app retaining
translations across an upgrade. The runner uses each frontend's native controls
and the public config-entry API to observe reload completion.

A live camera discovery attempt returned the integration's complete-snapshot
failure form during validation. A later run passed. The runner permits one native
Retry if initial discovery fails, then fails the check if the source remains
unavailable. This does not turn failed responses into successful snapshots.

The runner's `finally` block stops the temporary HA process on normal completion, exceptions and handled interrupts, escalating from graceful interrupt to kill only for that child if needed. Its temporary configuration, owner and authentication storage are removed. The port was confirmed closed after testing. Browser/HA log files and screenshots remain ignored. Existing Home Assistant installations, host services and host configuration are not used.

This check needs public API and browser download access. Source changes, camera unavailability, catalogue changes or package URLs disappearing can cause a live smoke failure; the mocked tests remain the reproducible behavior checks. Debian browser libraries are version/checksum-pinned and extracted without package installation, but their public mirror retention is outside this repository's control.

## Interactive HACS lifecycle check

`scripts/smoke-ui --hacs` prepares a separate disposable HA 2026.9.4 instance on
`127.0.0.1:18125` with the official HACS 2.0.5 release ZIP, verified against its
pinned SHA256. It starts HACS's ordinary config flow and prints a GitHub device
authorization URL and code. Complete the [official HACS authorization procedure](https://www.hacs.xyz/docs/use/configuration/basic/)
within fourteen minutes. The runner does not accept a personal access token,
reuse another installation's credentials or edit HACS's stored state.

After authorization, the scenario uses HACS's native frontend websocket commands
to add this custom repository, download 0.7.2, upgrade to 0.7.3 and uninstall.
It waits for `hacs/info` to report completed startup and an idle queue before
repository operations, and checks the installed version again after restarts.
HA's config-entry `loaded` state alone does not establish that HACS is ready.
It creates weather, camera and route subentries through the real HA frontend,
restarts the temporary process after code changes, compares registry identities,
checks recovery and route reconfiguration, removes a weather station and route,
then removes the parent. Logs, screenshots and a successful `lifecycle.json`
remain under ignored `.tools/smoke-results-hacs`; temporary configuration and local
authentication storage are removed when the runner exits, including on failure.

The complete scenario passed on 2026-10-04 with HACS 2.0.5 and HA 2026.9.4.
HACS reported numbered releases before and after the upgrade, and retained the
installed version across process restarts. All 12 entity IDs/unique IDs, four
device identities and four subentry identities survived. Entities recovered,
the existing route could be saved again, and source/route removal left the
remaining sources available. Parent removal cleared its registry entries;
HACS uninstall removed the component files. After another restart, neither HA
nor HACS reported the integration installed. The temporary instance stopped and
its configuration and local authentication storage were removed.

An uninstalled custom repository may disappear from HACS's repository listing
after restart. The check accepts either absence or an explicitly uninstalled
listing; it also independently checks that component files and the HA entry are
gone. This live, interactive scenario is separate from CI and the local HACS
schema validator. It uses HACS's real download/uninstall code, with its frontend
websocket API driving those operations; the HA configuration forms use a browser.

The installed 0.7.2 and 0.7.3 runs logged a weather device-name refresh deprecation
from HA 2026.9.4. Version 0.7.4 replaces `DeviceRegistry.async_get_device` with
the public `async_entries_for_config_entry` helper, supported by both tested
targets. Its regression tests pass on both versions; the browser and interactive
HACS lifecycle scenarios were not repeated for this isolated registry change.

A separate one-off check using the public 0.7.2 and 0.7.3 GitHub release archives
passed on HA 2026.9.4 on 2026-10-04. It installed 0.7.2 into a disposable instance,
created two weather stations, a camera and a route through the frontend, stopped
HA, replaced the component with 0.7.3, and restarted the same configuration. All
12 entity IDs/unique IDs, four devices and four subentry identities were retained
and entities became available again. Saving the existing route preserved those
identities. Removing one station and the route left the other sources available;
removing the parent cleared its entity/device registry entries. This verifies
the integration's live upgrade/removal behavior, but not HACS's download or
uninstall handling.

## Upgrade investigation (2026-10-03)

The original 0.4.2 smoke check had two gaps: HA was launched from the repository,
which could shadow the extracted package, and the cache check explicitly fetched
and merged fresh translations. That bypassed whether HA normally refreshes them.
The runner now isolates the child working directory and no longer injects
translation resources. The earlier cache check did not establish upgrade behavior.

A separate disposable HA 2026.9.4 test downloaded the public GitHub archives for
0.3.0 (`8bd50fb`) and 0.4.2 (`9384237`), created a weather entry with the old code,
and opened a Bokmål subentry flow. It then stopped HA, installed the new archive,
and restarted HA with the same configuration and browser tab. The test used an isolated
configuration and left existing installations and host services unchanged.

The unchanged browser tab reproduced lowercase `county` and `municipality`,
English **Change county**, and the old attribution with a `kartverket_url`
`MISSING_VALUE` error. Refreshing the same tab produced **Fylke**, **Kommune**,
**Værstasjon**, no old description, and working **Endre kommune** navigation with
the previous municipality retained. Thus replacing descriptions with empty strings
is insufficient until the browser actually fetches the new resources.

The [frontend translation cache](https://github.com/home-assistant/frontend/blob/20260826.7/src/state/translations-mixin.ts)
tracks explicitly loaded integrations separately from categories loaded for all
configured integrations. Reconnection only refreshes categories marked as loaded
for all configured integrations. Opening another flow can therefore reuse the
old integration-specific resources. This investigation reproduces a frontend cache failure
mechanism; it does not establish upgrade behavior for every frontend version.

To check this manually, keep a setup browser tab open across an integration
update and HA restart, then compare the source forms before and after refreshing
the browser. A fresh private browser window is a useful independent check. The
backend must first be restarted to load the installed Python code. This is not a
reason to remove configured sources or reinstall the integration.

## Distribution and validation limits

Numbered GitHub releases are distributed through a HACS custom repository; see the [installation guide](custom-repository-test.md) and [release guidance](releases.md). HACS default-list submission is separate. Automated checks cover the three locked targets above, not every intervening or beta HA version. The interactive HACS lifecycle scenario and long-running live recovery remain outside the deterministic CI suite. Route scheduling and entry unload/reload are covered by mocked tests on all three targets. Area monitors and automatic physical-source ownership remain future work; see [route details](route-forecasts.md).

The native picker tests cover all four parent/subentry source paths, actual HA form serialization, populated region filtering, invalid/out-of-region source IDs, missing/malformed index data, and new, moved or coordinate-free sources. Cache tests cover TTL expiry, shared flow reuse, copied snapshots, simultaneous flows, cancellation, independent families and failed/incomplete pagination without publishing partial data. Geography never runs during setup or entity polling. [Source and behavior details](geographic-selection.md).

For 0.6.1, route field/menu/action translations are checked through HA’s translation loader in English and Bokmål, for both initial setup and subentries. Tests cover mixed endpoints, moved/deleted/unavailable zones and stable route identities. If a fresh browser renders labels correctly while the companion app retains old text, refresh the app frontend cache using its supported settings.
