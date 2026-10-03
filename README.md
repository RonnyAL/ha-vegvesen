# Statens vegvesen for Home Assistant

Custom integration with domain `vegvesen`. The next installation target is a **HACS custom repository**; inclusion in HACS's default list is deferred. Manually selected road weather stations and road camera stills are implemented. Geographic monitors remain future work; this is not a published release. See the [custom-repository test guide](docs/custom-repository-test.md) for prerequisites, installation, updates and removal. The reviewed source must be available on a public GitHub repository before HACS can fetch it.

Add **Statens vegvesen** from Settings → Devices & services and choose a weather station or road camera as the first source. Labels include names, direction where available, and source identifiers. Use the parent entry's **Add weather station** or **Add road camera** action for further selections; an existing source ID cannot be selected twice within its source type. Remove individual source subentries to remove their entities. Additions and removals reload the parent entry.

Each station has one device and two sensors: air temperature (native °C) and observation time. Device and entity identifiers use the exact `REFERENCE_ID`, including leading zeroes. Names, coordinates, and GeoServer row identifiers do not determine identity.

Weather polls every ten minutes using one filtered request chain for the selected IDs. Null or omitted measurements are **unknown**. A failed, malformed, or incomplete refresh makes weather sensors **unavailable**, retaining the previous internal snapshot until recovery. A station absent from a successful complete snapshot is unavailable individually. Unusual numeric source values are preserved. Home Assistant may display temperatures in the user's preferred units and timestamp states in UTC.

Each camera has one device, a cached still-camera entity, and a raw **Source availability** sensor. Camera IDs include their direction suffix. Selected camera metadata and available JPEGs poll once a minute; frontend requests use the memory cache. A failed JPEG makes only that camera unavailable, while its source-status sensor stays available. Metadata failures make the CCTV family unavailable. Weather and cameras recover independently, including during mixed-entry setup. Publication/update timestamps are metadata attributes, not image capture times. See [camera API and behavior notes](docs/camera-milestone.md).

## Development

The locked test environment is **CPython 3.14.8**, **Home Assistant 2026.9.4**, and **pytest-homeassistant-custom-component 0.13.367**, managed with **uv 0.12.22**. `pyproject.toml` describes development tooling, not a Python requirement imposed on users' HA installations. Debian's system Python is not used for the virtual environment.

From this repository, with uv already installed:

```bash
VEGVESEN_UV=/home/dev/.local/bin/uv scripts/setup
VEGVESEN_UV=/home/dev/.local/bin/uv scripts/check
```

`setup` creates `.venv` and installs `uv.lock` with `--locked`. `check` runs Ruff lint, Ruff formatting verification, and the mocked pytest suite. CI runs the same scripts with the same Python and uv versions. The scripts use a repository-local uv cache and fall back to `$HOME/.local/bin/uv` when uv is absent from PATH. Separate checks:

```bash
scripts/lint
UV_CACHE_DIR="$PWD/.cache/uv" /home/dev/.local/bin/uv run --locked --no-sync pytest
```

To intentionally format edits:

```bash
UV_CACHE_DIR="$PWD/.cache/uv" /home/dev/.local/bin/uv run --locked --no-sync ruff format .
```

Tests disable external sockets and mock HTTP. They cover pagination atomicity, parsing, flows, duplicates, identities, unknown/unavailable states, rate limiting, automatic setup retry, recovery, subentry changes, and unloading including an in-flight poll. A test-only response-factory adapter supplies the stream writer argument omitted by aioresponses 0.7.9 for HA's aiohttp 3.14; production dependencies remain unchanged. The dev lock also includes HA's camera platform requirement, PyTurboJPEG 1.8.3, and pins its setuptools build dependency. Native host libraries are not installed by setup.

The minimum supported HA version is **2025.12.0**, distinct from the primary development target. It supplies subentries with unique IDs and entity registration, typed entry runtime data, coordinator lifecycle integration, and [`UpdateFailed(retry_after=...)`](https://developers.home-assistant.io/blog/2025/11/17/retry-after-update-failed/). The complete suite also passes against this minimum using **CPython 3.13.11** and **pytest-homeassistant-custom-component 0.13.298**. Ruff targets Python 3.13 syntax.

```bash
scripts/check-minimum
scripts/validate-hassfest
scripts/validate-hacs
```

The minimum environment has a separate `environments/minimum/uv.lock` and `.venv`. Its pycares pin avoids an incompatible newer transitive dependency of HA's aiodns. The old lru-dict requirement needs a native build on Python 3.13; a pinned Zig compiler runs inside uv's isolated build environment, with caches and the managed interpreter inside the repository. No host compiler or system Python change is required. Hassfest uses checksum-pinned HA 2026.9.4 source. Local HACS checks use the official HACS 2.0.5 manifest schemas plus package structure and image checks; they do not validate remote repository metadata or releases. CI runs these same commands and a separate remote HACS action with PR comments disabled.

The explicit live UI smoke test is available for Debian 12 amd64:

```bash
scripts/smoke-ui
```

This installs locked optional frontend/browser dependencies, extracts checksum-pinned Debian packages into `.tools`, builds and extracts the runtime package, and starts a disposable HA instance bound to `127.0.0.1:18123`. It creates an ephemeral test owner, selects public fixture stations/cameras through the real frontend, verifies entity states and a cached JPEG, then stops HA and removes its temporary configuration even on test failure. Screenshots and logs stay in ignored `.tools/smoke-results`. It uses live public APIs, so source changes and outages can fail this optional check. Existing port occupancy fails before starting anything. The normal mocked checks do not start an HTTP server. See [validation details](docs/validation.md).

No standalone HA process is started by setup or checks; pytest exercises HA in its temporary test environment. `scripts/develop` is an explicit foreground-only launcher for the repository's ignored runtime configuration, bound to `127.0.0.1:18123`; reserve running it for a separately approved development session. The optional devcontainer configuration does not auto-start HA. Do not use the household instance or modify existing Docker services for development.

`.venv`, caches, runtime files, `first_output.md`, `codex-session-*.md`, and `conversation_exports/` are excluded from Git. Keep all conversation exports in that ignored directory. Do not add credentials or personal locations to tracked files.

## Data and licensing

**Data provided by Statens vegvesen.** The official [CCTV dataset catalogue](https://dataut.vegvesen.no/en/dataset/webkamera) and [weather data catalogue](https://dataut.vegvesen.no/nb/dataservice/vaerdata-malinger-api) identifies NLOD licensing, and the [DATEX publication documentation](https://www.vegvesen.no/en/fag/technology/open-data/a-selection-of-open-data/what-is-datex/publications/) requires source attribution. The public OGC representation has been observed to work without credentials; the separate DATEX XML service requires registration. See [API and architecture notes](docs/weather-milestone.md) and [fixture provenance](tests/fixtures/README.md) for verified behavior and limitations.

The integration retains the scaffold's [MIT license](LICENSE), including Joakim Sørensen's copyright notice. It is based on [ludeeus/integration_blueprint](https://github.com/ludeeus/integration_blueprint).

Local HACS packaging includes English and Norwegian Bokmål translations, original generic road/weather icons, the preserved MIT license and an attribution notice in the installed component directory. GitHub availability and actual custom-repository installation/update testing remain outstanding. HACS default-list submission is deferred. No monitor framework or camera video streaming is included.
