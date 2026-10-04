# Development

The locked test environment is **CPython 3.14.8**, **Home Assistant 2026.9.4**, and **pytest-homeassistant-custom-component 0.13.367**, managed with **uv 0.12.22**. `pyproject.toml` describes development tooling, not a Python requirement imposed on users' HA installations. The virtual environment uses a uv-managed interpreter independently of system Python.

From this repository, with uv already installed:

```bash
scripts/setup
scripts/check
```

`setup` creates `.venv` and installs `uv.lock` with `--locked`. `check` runs Ruff linting, Ruff formatting verification and the mocked pytest suite. CI runs the same scripts with the same Python and uv versions. Native config-flow selectors require no integration JavaScript or Node tooling. The scripts use a repository-local uv cache and fall back to `$HOME/.local/bin/uv` when uv is absent from PATH. Separate checks:

```bash
scripts/lint
UV_CACHE_DIR="$PWD/.cache/uv" uv run --locked --no-sync pytest
```

To intentionally format edits:

```bash
UV_CACHE_DIR="$PWD/.cache/uv" uv run --locked --no-sync ruff format .
```

Tests disable external sockets and mock HTTP. They cover pagination atomicity, parsing, flows, duplicates, identities, unknown/unavailable states, rate limiting, automatic setup retry, recovery, subentry changes, and unloading including an in-flight poll. Route scheduling tests advance HA’s timer against mocked HTTP responses to check clock alignment, hour rollover and server retry delays without waiting in real time. A test-only response-factory adapter supplies the stream writer argument omitted by aioresponses 0.7.9 for HA's aiohttp 3.14; this adapter does not change production HTTP behavior. Route geometry uses pinned PyProj 3.8.0 and Shapely 2.1.2, also present in both test locks and the integration manifest. The dev lock also includes HA's camera platform requirement, PyTurboJPEG 1.8.3, and pins its setuptools build dependency. Native host libraries are not installed by setup.

The minimum supported HA version is **2025.12.0**, distinct from the primary development target. It supplies subentries with unique IDs and entity registration, typed entry runtime data, coordinator lifecycle integration, and [`UpdateFailed(retry_after=...)`](https://developers.home-assistant.io/blog/2025/11/17/retry-after-update-failed/). The complete suite also passes against this minimum using **CPython 3.13.11** and **pytest-homeassistant-custom-component 0.13.298**. Ruff targets Python 3.13 syntax.

```bash
scripts/check-minimum
scripts/check-beta
scripts/validate-hassfest
scripts/validate-hacs
```

The minimum environment has a separate `environments/minimum/uv.lock` and `.venv`. Its pycares pin avoids an incompatible newer transitive dependency of HA's aiodns. The old lru-dict requirement needs a native build on Python 3.13; a pinned Zig compiler runs inside uv's isolated build environment, with caches and the managed interpreter inside the repository. No host compiler or system Python change is required. Hassfest uses checksum-pinned HA 2026.9.4 source. Local HACS checks use the official HACS 2.0.5 manifest schemas plus package structure and image checks; they do not validate remote repository metadata or releases. CI runs these same commands and a separate remote HACS action with PR comments disabled.

The explicit live UI smoke test is available for Debian 12 amd64:

```bash
scripts/smoke-ui
scripts/smoke-ui --minimum
scripts/smoke-ui --beta --rollback
# Interactive GitHub authorization is required for this separate HACS check.
scripts/smoke-ui --hacs
```

This installs locked optional frontend/browser dependencies, extracts checksum-pinned Debian packages into `.tools`, builds and extracts the runtime package, and starts a disposable HA instance bound to `127.0.0.1:18123`. It creates an ephemeral test owner, selects public fixture stations/cameras and a Trondheim–Orkanger route through the real frontend, verifies entity states and a cached JPEG, then stops HA and removes its temporary configuration even on test failure. Screenshots and logs stay in ignored `.tools/smoke-results`. It uses live public APIs, so source changes and outages can fail this optional check. Existing port occupancy fails before starting anything. The normal mocked checks do not start an HTTP server. See [validation details](validation.md).

`--minimum` installs the minimum environment's locked optional frontend group and
runs the same browser scenario on port 18124, with results in
`.tools/smoke-results-minimum`. `--hacs` uses official HACS 2.0.5 on port 18125;
complete its printed GitHub device authorization to exercise the real custom
repository install/upgrade/removal scenario. Its results stay in
`.tools/smoke-results-hacs`. Run these optional checks sequentially: dependency
syncs can remove groups needed by another running check. Both backend targets
and frontend targets have passed, as has the interactive HACS 2.0.5 scenario on
the primary target. Consult validation evidence for its scope and limitations.

No standalone HA process is started by setup or checks; pytest exercises HA in its temporary test environment. `scripts/develop` is an explicit foreground-only launcher for the repository's ignored runtime configuration, bound to `127.0.0.1:18123`; run it only for an intentional development session. The optional devcontainer configuration does not auto-start HA. Keep development separate from existing Home Assistant installations and host services.

Dependencies, virtual environments, caches, runtime files and conversation exports are excluded from Git. Keep conversation exports in the ignored `conversation_exports/` directory. Do not add credentials or personal locations to tracked files.

## Releases and native platform behavior

Follow the [release and lifecycle guidance](releases.md). Use ordinary GitHub releases from validated commits for numbered HACS updates. Runtime code upgrades require a Home Assistant restart; normal config-entry reload support does not replace imported Python code. Prefer official HA/HACS mechanisms and explain unsupported behavior instead of implementing bypasses.

## Updating source geography

The runtime package includes public source IDs, coordinates and administrative names in `source_geography.json`. Setup uses a live source catalogue and does not query Kartverket. Regenerate the index before a release when public sources or administrative boundaries change:

```bash
UV_CACHE_DIR="$PWD/.cache/uv" uv run --locked --no-sync python -u scripts/build-source-geography.py
```

This makes public API requests with at most four concurrent point lookups, coalesces identical coordinates, and replaces the file only after complete catalogues and successful lookups. Review the generated changes and retain Kartverket attribution. Runtime labels require an exact source-ID and coordinate match; new or moved sources remain selectable under unknown county/municipality, without guessed geography. See [geographic selection](geographic-selection.md).

The [route-map beta](route-maps.md) has a third locked target in
`environments/beta`, using HA 2026.10.0b0 and its matching test package. Its PNG
renderer uses Pillow already provided by HA core; it adds no host dependency.
The native image and signed-path APIs are also available at the existing minimum.
