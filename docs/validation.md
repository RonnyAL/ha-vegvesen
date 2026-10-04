# Compatibility, packaging and isolated UI validation

## Tested targets

| Purpose | Home Assistant | Python | pytest custom-component package | Lock |
| --- | --- | --- | --- | --- |
| Primary development | 2026.9.4 | 3.14.8 | 0.13.367 | `uv.lock` |
| Minimum supported | 2025.12.0 | 3.13.11 | 0.13.298 | `environments/minimum/uv.lock` |

Both run the same 285 mocked tests with 96% integration statement coverage. The minimum is justified by the runtime APIs used, particularly [`UpdateFailed(retry_after=...)`](https://developers.home-assistant.io/blog/2025/11/17/retry-after-update-failed/), config subentries, source unique IDs, subentry entity/device registration, entry runtime data and coordinator lifecycle hooks. Earlier versions have not been claimed or tested. Patch Python versions here are development pins, not integration requirements imposed on an HA-managed installation.

The route scheduler tests advance HA’s actual timer with mocked HTTP responses. They cover hour/half-hour boundaries, midnight and the UTC hour of Oslo’s daylight-saving transition, manual refresh alignment, a request crossing an hour, unchanged states, failure/recovery, Retry-After spanning a boundary, disabled polling and unloading. No live half-hour wait or household HA is needed.

The [0.6.3 config-flow review](config-flow-review.md) records native API choices and fixes. New mocked tests cover pending-flow cancellation, progress revisits, cleared optional selectors, numeric validation and translated progress/errors on both supported targets.

The [0.6.4 API constraint review](route-forecasts.md#api-constraint-review--064)
distinguishes documented request requirements, observed forecast availability
and integration UI limits. Additional tests cover documented/live routing error
formats, correcting off-network map/zone endpoints in parent/subentry flows,
retained drafts and successful retry, and an unpublished forecast without fallback.

The Bokmål test configures HA with language `nb`, checks translated temperature and observation names, resolves both translated subentry actions through HA's translation loader, and verifies source-based entity identity remains intact.

The minimum's aiodns 3.5.0 cannot import with pycares 5, so its environment explicitly pins pycares 4.11.0. The matching test package pins HA 2025.12.0. Its lru-dict 1.3.0 has no CPython 3.13 wheel; a Zig 0.15.2 compiler builds it locally. The wrapper omits CPython's `--exclude-libs,ALL` linker flag, which Zig cannot parse and which is unnecessary for this extension without linked static archives. Other arguments are preserved.

Optional frontend dependencies require two further native builds on Python 3.14. Their isolated build environments use the same pinned Zig compiler. Setuptools, wheel and pybind11 build dependencies are constrained explicitly. All compilers, managed Python 3.13, environments, downloaded source archives, native libraries and caches remain inside ignored repository directories. Debian's Python and packages are unchanged.

## Reproduce the checks

Use uv 0.12.22. Native source selection requires no integration JavaScript or Node toolchain. These scripts fall back to `/home/dev/.local/bin/uv` when necessary; `VEGVESEN_UV` can override it.

```bash
scripts/setup
scripts/check
scripts/check-minimum
scripts/validate-hassfest
scripts/validate-hacs
scripts/smoke-ui
git diff --check
```

The first five checks match CI. The live UI smoke test is an explicit local check for Debian 12 amd64, separate from deterministic mocked tests. Normal setup, test and packaging scripts never start HA or use Docker. Optional dependency groups share the primary `.venv`; `uv sync` installs the selected groups and removes unselected ones. Run `scripts/smoke-ui` again to restore the browser/frontend group after ordinary setup or validation.

## Packaging validation

`scripts/validate-hassfest` runs all Hassfest validators from official [HA 2026.9.4 source](https://github.com/home-assistant/core/tree/2026.9.4/script/hassfest), using a SHA256-checked source archive. Result: one integration, zero invalid integrations, no warnings. This exposed and corrected missing `entry_type` and `initiate_flow.user` subentry translations and removed obsolete title keys.

`scripts/validate-hacs` imports [official HACS 2.0.5 manifest schemas](https://github.com/hacs/integration/blob/2.0.5/custom_components/hacs/utils/validate.py) without loading HACS's startup code. It validates both manifests, the single-domain package layout, essential files and local PNG dimensions. Result: passed. The generic road/weather icons are original artwork under the project's MIT license; they are not Statens vegvesen's logo. The editable SVG accompanies 256px and 512px PNGs. Local assets follow [HA's file structure](https://developers.home-assistant.io/docs/creating_integration_file_structure/#brand-images---brand) and [HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/).

The separate remote HACS action runs for public repositories with `comment: false` and no ignored brands check. It inspects GitHub repository content and metadata; its results are available in the repository's Actions tab after pushing. Private repositories are skipped because HACS cannot install them. Description and topic checks for the default list are deferred with that submission. Its pinned action wrapper still uses HACS's upstream `main` Docker image, so that remote check is not reproducible to the same degree as the pinned local checks. A local pass is not a claim of HACS listing or successful HACS installation.

## UI smoke test

The packaged 0.6.4 check passed on 2026-10-04, including native progress,
cached discovery, English/Bokmål source and route forms, zone/map endpoints,
reconfiguration and live entities. Initial weather/camera lists opened in about
0.6/0.8 seconds respectively and cached weather discovery in 0.07 seconds in this run; these are
observations, not API or UI performance guarantees. The runner waits for HA's
parent reload before opening the next subentry flow, since HA disables its parent
chooser during that reload.

The runner checks port 18123 is free, starts a disposable HA 2026.9.4 instance on `127.0.0.1`, creates an ephemeral owner, and confirms the loopback HTTP settings. Default onboarding integrations and analytics are skipped. Its coordinates are deliberately zero and are unrelated to source selection. It builds a runtime-only ZIP and extracts the custom component into the temporary configuration. The HA child runs with that directory as its working directory and Python's `-E` option, so the repository and an inherited development `PYTHONPATH` cannot shadow the installed package. The package includes English/Bokmål translations, the original license and data attribution.

The first-use test opens the native overview and selects **Trøndelag → Orkland**,
then **Fv 714 Våvatnet (1629006)** and **Fv 65 Bye (1629004)** together. It revisits
both region editors, retains the source draft and creates the parent with two
weather subentries through **Add**. It then adds **Møre og Romsdal → Herøy →
Rundebrua — Runde (3000047_2)** through **Add road cameras**. It checks the
readable selected source chips and visible edit actions, switches to Bokmål,
refreshes normally, and checks both families' field labels and overview actions.
No translation resources are manually injected. Screenshots and timing results
remain ignored in `.tools/smoke-results`.

The runner also saves the public Trondheim–Orkanger route through native map/coordinate inputs, checks its editable overview and proposal selector, then exercises the full Bokmål route flow: named zones, a mixed zone/map pair, all four overview labels, the route proposal label, retained choices when editing, and an existing route's reconfigure action. The result has three physical devices, one route service device and twelve entities. Six route forecast states must become available against the live API. The test checks weather
and camera states, retrieves a JPEG through HA's camera proxy, opens the camera
details dialog, and checks the rendered image. It also reopens a weather flow
to exercise cached discovery. The minimal test instance has no recorder or
integration diagnostics handler; frontend requests for `recorder/info` and
`diagnostics/get` report unsupported-command/domain errors. They do not prevent
picker, entity or image checks. This targets the primary frontend and a refreshed
browser, not an open app retaining translations across an upgrade. Minimum-version
backend behavior is covered by the same mocked tests.

The runner's `finally` block stops the temporary HA process on normal completion, exceptions and handled interrupts, escalating from graceful interrupt to kill only for that child if needed. Its temporary configuration, owner and authentication storage are removed. The port was confirmed closed after testing. Browser/HA log files and screenshots remain ignored. No household HA, existing Docker services or host configuration are used.

This check needs public API and browser download access. Source changes, camera unavailability, catalogue changes or package URLs disappearing can cause a live smoke failure; the mocked tests remain the reproducible behavior checks. Debian browser libraries are version/checksum-pinned and extracted without package installation, but their public mirror retention is outside this repository's control.

## Upgrade investigation (2026-10-03)

The original 0.4.2 smoke check had two gaps: HA was launched from the repository,
which could shadow the extracted package, and the cache check explicitly fetched
and merged fresh translations. That bypassed whether HA normally refreshes them.
The runner now isolates the child working directory and no longer injects
translation resources. The earlier cache check did not establish upgrade behavior.

A separate disposable HA 2026.9.4 test downloaded the public GitHub archives for
0.3.0 (`8bd50fb`) and 0.4.2 (`9384237`), created a weather entry with the old code,
and opened a Bokmål subentry flow. It then stopped HA, installed the new archive,
and restarted HA with the same configuration and browser tab. No household
instance or host services were used.

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
old integration-specific resources. This investigation reproduces a failure
mechanism; the user's exact HA version and browser state still need confirmation.

To check this manually, keep a setup browser tab open across an integration
update and HA restart, then compare the source forms before and after refreshing
the browser. A fresh private browser window is a useful independent check. The
backend must first be restarted to load the installed Python code. This is not a
reason to remove configured sources or reinstall the integration.

## Remaining distribution work

The immediate target is user testing through a HACS custom repository, described in the [installation guide](custom-repository-test.md). Default-list submission is deferred. Numbered GitHub releases now provide the normal user update path; `main` remains available for development testing. See [release and lifecycle guidance](releases.md). The repository is now public and the user reports the initial HACS installation working. The user reports 0.6.0 route operation working on HA 2026.10.0b0; that beta is not an automated test target. Actual HACS 0.6.4 upgrade/removal testing remains pending. The route schedule is covered by mocked timer tests on both targets. Longer-running live recovery observations and a minimum-version frontend smoke test remain future work. Saved route forecasts are implemented; area monitors and automatic physical-source ownership/deduplication remain future work. See [route details](route-forecasts.md).

The native picker tests cover all four parent/subentry source paths, actual HA form serialization, populated region filtering, invalid/out-of-region source IDs, missing/malformed index data, and new, moved or coordinate-free sources. Cache tests cover TTL expiry, shared flow reuse, copied snapshots, simultaneous flows, cancellation, independent families and failed/incomplete pagination without publishing partial data. Geography never runs during setup or entity polling. [Source and behavior details](geographic-selection.md).

For 0.6.1, route field/menu/action translations are checked through HA’s translation loader in English and Bokmål, for both initial setup and subentries. Tests cover mixed endpoints, moved/deleted/unavailable zones and stable route identities. The user confirmed 0.6.0’s blank route labels occurred only in the companion app, with the browser rendering correctly; clearing the app frontend cache is the remedy, not an integration-specific frontend patch.
