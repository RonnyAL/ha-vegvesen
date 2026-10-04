# Config-flow review — 0.6.3

This is the historical 0.6.3 review. The source overview UX was superseded in
0.7.0 by the [three-step source wizard](geographic-selection.md); cancellation,
atomic validation and route-flow findings still apply.

Reviewed on 2026-10-04 against the project's native HA/HACS policy, official
[config-flow and subentry guidance](https://developers.home-assistant.io/docs/core/integration/config_flow/),
[data-entry flow documentation](https://developers.home-assistant.io/docs/data_entry_flow_index/),
and the implementations in both locked HA targets (2025.12.0 and 2026.9.4).
Current online documentation can describe APIs newer than the minimum; changes
must also work against the supported source versions. This review adds no newer
HA requirement or dependency.

## Retained native design

| Area | Finding |
| --- | --- |
| Parent and subentries | One public-service parent with weather, camera and route subentries follows HA's model for independently configured locations/sources. No parent-wide geography or credentials are invented. |
| Identity | Physical source IDs remain immutable identities; routes retain a local UUID when edited. Duplicate checks run before validation and again immediately before saving. |
| Menus and selectors | Editable overview menus, native dropdowns and map selectors are supported. Live dependent fields and a configurable form Back button are not exposed by these APIs; no custom frontend is introduced. |
| Zone selection | A native select lists HA zones by friendly name/ID alongside the translated map option. It works on the minimum version; a newer choose-selector widget is unnecessary. |
| Batch creation | Initial setup supplies HA's `subentries` result. An existing parent's batch uses the public `async_add_subentry` API and the normal single-subentry result after complete validation. No network await occurs during persistence. |
| Reconfiguration | Routes use `_get_reconfigure_subentry` and `async_update_and_abort`. The registered parent update listener handles reloads, so the flow must not also request a reload. Station/camera identity changes are handled by removing and adding physical sources. |
| Reload lifecycle | The public update listener coalesces synchronous batches, awaits HA's reload, and checks for additions during setup I/O. Existing tests cover both cases and resource cleanup. A single unobserved scheduled reload would lose that reconciliation. |
| I/O and caching | Requests use HA's shared aiohttp session, bounded timeouts, strict complete pagination and independent family caches. No blocking network I/O or custom frontend cache manipulation is present. |
| Translations | English/Bokmål flow, selector, progress and error resources use HA's translation system. No runtime injection or workaround for stale companion-app resources is introduced. |

## Corrections

1. **Native progress and cancellation.** Discovery, final source validation and
   route calculation now pass tasks to `async_show_progress`, then advance through
   `async_show_progress_done`. HA cancels the registered task when a pending flow
   is aborted. Reopening progress does not spawn another request. Background tasks
   never persist selections: the live flow performs the final duplicate check and
   save. Previously an inline batch-validation request could outlive a cancelled
   flow and reach direct subentry writes. This uses HA's documented task lifecycle,
   with no custom scheduler, frontend code or cancellation registry.
   Immediately completed cached work returns its next form/menu directly.
   It does not emit an initial `progress_done` response or a progress event before
   the browser can subscribe. Pending work uses HA's normal progress lifecycle.
2. **Clearable source drafts.** An optional selector now uses HA's
   `suggested_value` description for the previous selection and an empty default.
   If the frontend omits a cleared field, the old selection is not restored.
   Explicit empty lists also remain supported.
3. **Numeric input validation.** HA's `NumberSelector.step` controls widget
   increments; it does not enforce integer input. Fractional forecast offsets
   previously produced non-hourly API queries. Whole forecast hours and finite
   numeric settings are now checked before calculation with translated field
   errors. Invalid non-finite values are not echoed into JSON form defaults.
   These are user-configuration checks; source measurements remain unchanged.
4. **Route draft/error handling.** Reconfiguration makes a deep draft copy, and
   error forms are constructed through `async_show_form` rather than modifying
   an already constructed flow result. Saving keeps route/device/entity identity.

## Verification

The same 266 mocked tests pass on both locked targets, with 96% integration
statement coverage. New tests exercise all four weather/camera parent/subentry
paths, pending discovery and batch-validation cancellation, route calculation
cancellation for initial setup/add/reconfigure, progress revisit and immediate
cached results, cleared optional
fields, invalid numeric settings, serializable error forms and English/Bokmål
resources. Existing tests continue to cover duplicate races, atomic pagination,
retry, cache sharing, route edits, batch reloads and unloads.

See [validation.md](validation.md) for commands and packaged browser evidence.
The minimum-version frontend and companion-app cache behavior are not automated
UI targets; their behavior is not inferred from backend test passes. Existing
saved selections need no migration. Numeric validation applies when editing
settings; existing source observations are never corrected or clamped.
