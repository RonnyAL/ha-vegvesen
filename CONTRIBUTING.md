# Contributing

Read [AGENTS.md](AGENTS.md) and the [development instructions](docs/development.md). Work in the repository virtual environment and use isolated test instances. Leave system Python and existing installations and services unchanged.

Use supported native HA/HACS mechanisms and verify official guidance before designing alternatives. If the platform does not support a requested interaction or lifecycle behavior, explain the limitation and choose a supported alternative; do not work around it with monkey patches, custom Python hot reloaders or frontend internals. A config-entry reload is not a code upgrade. Follow the [release and lifecycle guidance](docs/releases.md) for versioned GitHub releases and restart requirements. The [config-flow review](docs/config-flow-review.md) documents the native flow choices and their regression coverage.

Run `scripts/setup` followed by `scripts/check`. These are also the CI commands. Ruff handles lint and formatting checks; tests use Home Assistant's custom-component test package and mocked network responses. When changing dependency pins, regenerate `uv.lock` using the pinned uv version and rerun the checks.

Run `scripts/check-minimum` for the independently locked HA 2025.12.0 environment. Update its lock with `UV_CACHE_DIR="$PWD/.cache/uv" UV_PYTHON_INSTALL_DIR="$PWD/.tools/python" uv lock --project environments/minimum` when changing its pins. Run `scripts/validate-hassfest` and `scripts/validate-hacs` for the same packaging validation used by CI. The optional `scripts/smoke-ui` uses live public APIs and a temporary local HTTP server; it is separate from the deterministic mocked CI suite. Details, isolation guarantees, and limitations are in [docs/validation.md](docs/validation.md).

`scripts/package` creates a deterministic local runtime archive and SHA256 file inside ignored `.tools/packages`. Keep the installed component's `LICENSE` byte-for-byte identical to the root license, and retain `NOTICE.md` for scaffold and data attribution. The smoke test extracts this archive rather than linking the development tree. Distribution uses numbered GitHub releases through a [HACS custom repository](docs/custom-repository-test.md). Submission to HACS's default list is a separate process.

Expose source data faithfully. Add meaningful tests for changed parser, flow, identity, availability, or lifecycle behavior. Do not add plausibility checks, clamping, outlier rejection, inferred corrections, or custom risk scores. Record the provenance of any public API fixtures. Keep credentials, personal locations, runtime files, and conversation exports out of tracked files.

Describe behavior changes and validation in pull requests. Report bugs through this repository's issues with reproduction steps and relevant logs, removing private details first.

The [public release review](docs/release-readiness.md) records the current readiness assessment, completed checks and remaining validation limits.

The integration is based on [ludeeus/integration_blueprint](https://github.com/ludeeus/integration_blueprint). Contributions use the existing [MIT license](LICENSE); preserve its copyright and license notice. Statens vegvesen source data has separate licensing and attribution requirements documented in the README.
