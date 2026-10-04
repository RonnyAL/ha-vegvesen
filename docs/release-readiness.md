# Public release review — 0.7.3 and 0.7.4

Reviewed on 2026-10-04. The code and package are technically ready for public
distribution through a HACS custom repository. No blocking runtime defect was
identified in this review. This verdict covers the tested targets and documented
feature scope; it is not a HACS default-list approval or a guarantee for every
HA version, installation architecture or upstream outage.

The full review and evidence below concern 0.7.3. The
[0.7.4 follow-up](#074-device-registry-follow-up) records the subsequent lookup fix
and its validation separately.

## Scope and corrections

The review covered all runtime modules, config/subentry flows, source parsing,
pagination, retry handling, scheduling, entity/device identity, unload/reload,
route actions, English/Bokmål strings, README, contributor documentation, issue
templates, manifests, dependency locks, workflows and packaged files.

Corrections made:

- Removed maintainer-specific environment paths, deployment references and
  individual support-session history from public documentation. Kept generic
  installation instructions, public fixture provenance and actual test evidence.
- Added a documentation rule to `AGENTS.md` so public text stays independent of
  private conversations and personal deployments.
- Simplified README instructions, identified the integration as community
  maintained, documented route-coordinate requests and clarified shared forecast
  rate limits. Contributor instructions use portable commands.
- Replaced inherited issue templates that requested full startup logs and an
  unsupported diagnostics download. Reports now request versions, reproduction
  steps and optional relevant logs with private details removed.
- Corrected route validation text that incorrectly required a name. Route-action
  failures now use native translated `ServiceValidationError` messages in English
  and Bokmål, following [HA's exception localization](https://developers.home-assistant.io/docs/internationalization/core/#exceptions).
- Made shared pagination errors source-neutral. No source values, identities,
  polling intervals or permission policies changed.

## Evidence

| Check | Result |
| --- | --- |
| HA 2026.9.4 / Python 3.14.8 | 314 mocked tests passed; 96% statement coverage |
| HA 2025.12.0 / Python 3.13.11 | Same 314 tests passed; 96% statement coverage |
| Ruff lint and formatting | Passed |
| Pinned Hassfest | Zero invalid integrations, no warnings |
| Local HACS schemas and package validation | Passed |
| Packaged HA 2026.9.4 browser smoke | Passed with live weather, camera and route APIs; English/Bokmål forms, icons and reconfiguration |
| Packaged HA 2025.12.0 browser smoke | Same frontend scenario passed against the separately locked minimum target |
| Public archive upgrade 0.7.2 → 0.7.3 | Passed on HA 2026.9.4: 12 entity identities, four devices and four subentries retained; reconfiguration and removal passed |
| Real HACS 2.0.5 install/upgrade/removal | Passed on HA 2026.9.4: numbered 0.7.2 → 0.7.3 upgrade, restarts, identity preservation, reconfiguration, source/parent removal and uninstall |
| Text and package inspection | No personal environment references or common credential markers found; private exports and runtime directories excluded |
| Translation resources | All 170 English/Bokmål string keys and placeholders match |
| Local Markdown links and issue-form YAML | Passed |
| Disposable instance cleanup | HA exited and its loopback port closed |

The package contains 30 runtime files. Its MIT license is byte-for-byte identical
to the original root license, and data attribution remains in `NOTICE.md` and the
README. Only the original road/weather icon is included. This review did not
rewrite repository history; the text inspection applies to the current source
tree and package. Pattern scans are supplementary checks, not proof that every
possible secret format has been detected.

Reproduce the checks using [validation.md](validation.md). Publish the matching
GitHub release only after the exact commit passes both **Checks** and **Validate**
in GitHub Actions, following [release guidance](releases.md).

## 0.7.4 device-registry follow-up

Replaced the deprecated weather device lookup with the public
`async_entries_for_config_entry` helper, indexing only devices owned by the
coordinator's config entry. This follows HA's
[entry-scoped device identity model](https://developers.home-assistant.io/blog/2026/07/21/device-registry-single-config-entry/)
and works on both tested targets without raising the minimum HA version.
Source-name changes still update the device's default name; user-assigned names,
device IDs and entity IDs are preserved.

On 2026-10-04, all 315 mocked tests passed on HA 2026.9.4 and HA 2025.12.0,
with 96% statement coverage. Regression checks reproduce the old warning and
cross-entry rename before the fix and pass after it. Existing missing-data,
recovery and identity checks also pass. Ruff, formatting, pinned Hassfest and
local HACS validation passed. Dependency versions are unchanged.

The browser and interactive HACS lifecycle evidence above remains specific to
0.7.3; those scenarios were not repeated for this isolated registry change.

## Remaining limits

- The backend and packaged browser scenarios cover both declared targets on
  Linux x86_64. The real HACS lifecycle scenario passed on HA 2026.9.4.
  Long-running live recovery and ARM64 installation remain unverified.
- HA's custom restrictive entity policies are not checked by the route response
  action. Ordinary built-in groups can read entities; the existing permission
  behavior is unchanged. See the [qualified finding](runtime-review.md#permissions-finding-clarified-behavior-unchanged).
- Statens vegvesen explicitly makes its [OGC services available without registration](https://www.vegvesen.no/fag/teknologi/apne-data/et-utvalg-apne-data/ogc-karttjenester/hva-er-ogc-karttjenester/).
  A collection-specific reuse licence for the road-segment forecast feed remains
  unverified. Its metadata and the inspected official documentation do not supply
  one. The technical release verdict does not establish those reuse terms;
  attribution is retained and no licence is inferred from another dataset.
- Forecast coverage, publication timing and API availability depend on the source.
  Large route queries can exceed the deadline; these fail without publishing
  partial data. There is no provider push feed verified for this collection.
- Distribution remains through a public HACS custom repository. Default-list
  submission is a separate process under [HACS's requirements](https://www.hacs.xyz/docs/publish/integration/).
