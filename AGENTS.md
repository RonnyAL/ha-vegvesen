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
- Write public documentation and UI text for all users. Do not include private
  conversations, maintainer-specific paths, personal deployment details or
  individual support-session history. Use public fixtures and generic examples.

See [release and lifecycle guidance](docs/releases.md) for verified behavior.

## Current scope

- WeatherSimple_v2 weather stations.
- CctvSimple_v2 road cameras.
- UI configuration with manual station/camera selection.
- Saved road routes with source road-condition forecasts.
- Optional automatic camera/weather discovery for route-card display, without
  automatic physical devices or entities.
- Stable source IDs for device and entity identity.
- HACS-compatible packaging.

Verify endpoints, field names, units, IDs, and pagination against actual
API responses before implementing mappings.

## Architecture constraints

- No integration-wide geographic restriction.
- Future area monitors have their own point and radius.
- Each route has its own route geometry and corridor.
- Routes are independent of configured areas.
- Avoid duplicating physical stations/cameras when monitors overlap.
- Area monitors and automatic source ownership remain future work.

## Environment

- Work inside this repository and its isolated development environment.
- Leave system Python, existing services, Docker configuration and host settings
  unchanged.
- Do not deploy to existing Home Assistant installations. Use disposable test
  instances for development and validation.
- Preserve the scaffold's license and required attribution.
