# Statens vegvesen Home Assistant integration

Integration domain: vegvesen.
User-facing name: Statens vegvesen.

## Principles

- Expose source data faithfully.
- Do not implement plausibility checks, outlier rejection, clamping,
  inferred corrections, or custom road-risk scoring in v1.
- Handle missing data and API failures explicitly using appropriate
  Home Assistant unknown/unavailable behavior.
- Prefer documented public APIs over scraping.
- Validate configuration against verified constraints of the specific endpoint.
  Distinguish API requirements, current data availability and integration UI
  limits; do not transfer constraints from a related but different dataset.
- Verify current Home Assistant conventions against official documentation.
- Use asynchronous I/O and DataUpdateCoordinator where appropriate.
- Add meaningful tests for parsing, config flow, and entity behavior.
- Keep credentials and personal locations out of tracked files.

## Home Assistant and HACS conventions

- Prefer supported, native Home Assistant and HACS mechanisms for UI,
  configuration, lifecycle, updates and distribution.
- Verify behavior against current official documentation and, when needed,
  upstream source for the supported versions before proposing an implementation.
- Do not reinvent existing mechanisms or bypass platform limitations with
  monkey patches, custom hot reloaders, cache manipulation or hidden frontend
  hooks. Explain a limitation and choose a supported alternative instead.
- Distinguish integration/config-entry reloads, frontend refreshes, Home Assistant
  process restarts and host reboots. Do not promise that reloading a config entry
  loads upgraded Python code or suppress HACS's restart requirement.
- Publish user-facing versions through ordinary GitHub releases with matching
  version tags and manifest versions. A tag alone is not a HACS release.
  Keep releases tied to validated commits, with concise user-facing release notes.
- Keep the README focused on installation and use; put contributor procedures
  and verification evidence in CONTRIBUTING.md and docs/.

See [release and lifecycle guidance](docs/releases.md) for verified behavior.

## Initial scope

- WeatherSimple_v2 weather stations.
- CctvSimple_v2 road cameras.
- UI configuration with manual station/camera selection.
- Stable source IDs for device and entity identity.
- HACS-compatible packaging.

Verify endpoints, field names, units, IDs, and pagination against actual
API responses before implementing mappings.

## Architecture constraints

- No integration-wide geographic restriction.
- Future area monitors have their own point and radius.
- Future route monitors have their own route geometry and corridor.
- Routes are independent of configured areas.
- Avoid duplicating physical stations/cameras when monitors overlap.
- Future features are architecture considerations, not initial scope.

## Environment

Development runs on a Debian VM that also hosts existing Docker services.
- Work inside this repository and its development environment.
- Do not modify existing services, Docker configuration, or host settings.
- Do not deploy to the household Home Assistant instance.
- Preserve the scaffold's license and required attribution.
