# Runtime review follow-up — 0.7.2

Reviewed against HA 2026.9.4 and the supported minimum, HA 2025.12.0.

## Server retry delays

HA's coordinator honors `UpdateFailed(retry_after=...)` during ordinary polling,
but its first-refresh path raises `ConfigEntryNotReady` before retaining that
delay. The parent deliberately permits healthy source families to load while
another fails. Previously, that failed family's first scheduled refresh could
send HTTP before the server's requested delay elapsed. Recreating a client on
entry reload or setup retry also discarded any client-side backoff.

The existing HA-scoped discovery cache now retains the weather/camera collection
client and routing/forecast client used by flows and coordinators. The collection
client records monotonic cooldown deadlines after HTTP 429. Early attempts raise
the remaining retry delay locally, without sending HTTP. This covers initial
setup, later pagination, discovery, final selection checks, manual refreshes and
entry reloads. HA remains the only scheduler; no sleeping tasks or timers are
added. Deadlines are memory-only and do not survive an HA process restart.

Cooldowns apply to the affected collection endpoint, or to an individual image
URL. Routing has a separate endpoint cooldown. This is a conservative local
scope, not a claim that the upstream service documents separate quotas. Weather,
camera metadata and forecast requests remain independent. Routes sharing the
forecast endpoint share its server-requested pause; unrelated request failures
remain local to their route. A request already in flight when another receives
429 cannot be recalled.

## Route action lifecycle

`vegvesen.get_route_forecasts` is registered once in `async_setup`, following
[HA's service-action guidance](https://developers.home-assistant.io/docs/dev_101_services/).
It remains registered during setup retry, reload and entry unload. Each call
resolves the route device's current loaded config entry and coordinator, rather
than retaining a runtime from a previous setup. Unavailable/unloaded routes raise
`ServiceValidationError`; the action never returns a failed snapshot as current.

## Weather names and identity

New weather selections save the source's station name alongside its ID. If the
station is absent during initial setup, entity creation uses that saved name.
Legacy entries use their selection title with the generated ` (<source ID>)`
suffix removed. This avoids an extra source-ID suffix in new entity IDs solely
because a station happened to be missing at startup.

After a complete successful refresh, source renames update the integration's
device name through HA's device registry. User-assigned device names and existing
entity IDs are preserved. There is no automatic rename of entity IDs already
created by an older release.

## Permissions finding clarified; behavior unchanged

HA has a documented backend [entity permission model](https://developers.home-assistant.io/docs/auth_permissions/)
with read/control/edit policies. However, its built-in administrator, user and
read-only groups all have entity read access in both supported test targets;
see the [built-in policies](https://github.com/home-assistant/core/blob/2026.9.4/homeassistant/auth/permissions/system_policies.py).
The ordinary [user-management UI](https://www.home-assistant.io/docs/configuration/user-configuration/)
does not offer per-entity read restrictions.

The review probe injected a custom deny-read policy into a test user. It showed
that the route action does not itself check such policies; it did not demonstrate
a privacy bypass between ordinary HA users. The original finding overstated its
practical severity for a standard installation. Compatibility with custom
restrictive policies remains a deferred consideration. This release adds neither
an administrator restriction nor a new permission policy.
