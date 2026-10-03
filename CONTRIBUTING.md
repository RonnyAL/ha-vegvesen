# Contributing

Read [AGENTS.md](AGENTS.md) and the [development instructions](README.md). Work in the repository virtual environment; do not modify the host Python, existing services, or household Home Assistant.

Run `scripts/setup` followed by `scripts/check`. These are also the CI commands. Ruff provides both linting and formatting; tests use Home Assistant's custom-component test package and mocked network responses. When changing dependency pins, regenerate `uv.lock` using the pinned uv version and rerun the checks.

Run `scripts/check-minimum` for the independently locked HA 2025.12.0 environment. Update its lock with `UV_CACHE_DIR="$PWD/.cache/uv" UV_PYTHON_INSTALL_DIR="$PWD/.tools/python" /home/dev/.local/bin/uv lock --project environments/minimum` when changing its pins. Run `scripts/validate-hassfest` and `scripts/validate-hacs` for the same packaging validation used by CI. The optional `scripts/smoke-ui` uses live public APIs and a temporary local HTTP server; it is separate from the deterministic mocked CI suite. Details, isolation guarantees, and limitations are in [docs/validation.md](docs/validation.md).

`scripts/package` creates a deterministic local runtime archive and SHA256 file inside ignored `.tools/packages`. Keep the installed component's `LICENSE` byte-for-byte identical to the root license, and retain `NOTICE.md` for scaffold and data attribution. The smoke test extracts this archive rather than linking the development tree. The current handoff target is [HACS custom-repository testing](docs/custom-repository-test.md), with default-list submission deferred.

Expose source data faithfully. Add meaningful tests for changed parser, flow, identity, availability, or lifecycle behavior. Do not add plausibility checks, clamping, outlier rejection, inferred corrections, or custom risk scores. Record the provenance of any public API fixtures. Keep credentials, personal locations, runtime files, and conversation exports out of tracked files.

Describe behavior changes and validation in pull requests. Report bugs through this repository's issues with reproduction steps and relevant logs, removing private details first.

The integration is based on [ludeeus/integration_blueprint](https://github.com/ludeeus/integration_blueprint). Contributions use the existing [MIT license](LICENSE); preserve its copyright and license notice. Statens vegvesen source data has separate licensing and attribution requirements documented in the README.
