# Test through a HACS custom repository

The next installation target is HACS **Custom repositories**. Inclusion in HACS's default list is deferred. HACS can fetch the integration from a public repository's default branch; a GitHub release is optional. See the official [custom repository instructions](https://www.hacs.xyz/docs/faq/custom_repositories/) and [integration packaging requirements](https://www.hacs.xyz/docs/publish/integration/).

## Before installing

- Home Assistant **2025.12.0 or newer**; the primary tested target is **2026.9.4**.
- HACS **2.0.5 or newer**, already installed by the user.
- The reviewed code must be available in a publicly accessible GitHub repository. Its default branch must contain `hacs.json` and `custom_components/vegvesen/`, with the old `integration_blueprint` directory removed.
- Use HA's existing managed Python. The repository's uv, Python, compiler, browser and test dependencies are development tools and are not needed on the installation host.

The repository URL is `https://github.com/RonnyAL/ha-vegvesen`. It must be publicly accessible before adding it in HACS. HACS documents that [private repositories are unsupported](https://www.hacs.xyz/docs/faq/private_repositories/). Committing or pushing code does not change GitHub repository visibility.

## Install and configure

Once the reviewed source is available on the public default branch:

1. Open HACS and choose the menu in the upper-right corner → **Custom repositories**.
2. Enter the repository URL, choose type **Integration**, and add it.
3. Find **Statens vegvesen** in HACS and download it. Without a release, HACS uses the default branch.
4. Restart Home Assistant using your normal UI controls.
5. Open **Settings → Devices & services → Add integration** and search for **Statens vegvesen**.
6. Select **Weather station / Værstasjon** or **Road camera / Veikamera**. Use the overview to choose county, municipality, then one or more sources. Each editor returns with **Done**; choose **Add** on the overview to save the batch. Try the visible **Change county** and **Change municipality** actions before saving. Only populated regions appear; labels retain source IDs and camera direction.
7. Use **Add weather station / Legg til værstasjon** and **Add road camera / Legg til veikamera** on the same parent entry to add other sources.

There is no API credential or integration-wide location setting. Geographic monitors are not implemented. Existing source names and statuses are kept as provided by Statens vegvesen; UI labels have English and Norwegian Bokmål translations.

## First test session

Record your HA version and integration version **0.6.1**, plus selected source IDs. These are public source identifiers, but your choice of sources can reveal locations of interest; omit them from public reports if needed.

| Check | Expected result |
| --- | --- |
| Source picker | Native county, municipality and source steps; populated regions only; translated labels; change-region choices return to previous selections |
| One station | One physical device, an air-temperature sensor and an observation-time sensor |
| One camera | One direction-specific device, a still camera and a raw source-availability sensor |
| Additional selections | All sources under one parent; an already selected source ID cannot be added twice |
| Source null or missing observation | Unknown measurement; zero and unusual numeric values preserved |
| Healthy mixed entry | Station readings and the camera still load independently |
| Normal refreshes | Weather nominally every ten minutes; camera metadata/still every minute; source timestamps may remain unchanged |
| Camera detail dialog | A source still is displayed; metadata publication/update times are not claimed as image capture times |
| Restart HA | Selections retained, same device/entity identities, fresh data fetched |
| Remove one source subentry | Its entities and unowned device removed; other sources remain configured |

Observe ordinary source failures if they occur; this test does not require disrupting the installation host's network or services. Request/metadata failures produce unavailable entities and recover on subsequent successful polls. A failed JPEG affects only that camera's image; its raw status sensor can still expose source metadata. Incomplete pagination fails the whole affected collection refresh. A missing station/camera in a complete successful snapshot is unavailable individually. These failure paths are covered by mocked tests.

## Troubleshooting

If HACS cannot add the repository, check the public URL and required layout first. A private repository or a default branch still containing the scaffold cannot install this integration correctly. If HA cannot find the integration after download, confirm the installed path is `<HA config>/custom_components/vegvesen/manifest.json`, restart HA, and check the HA logs.

If a source is unavailable, inspect its source status and the HA logs. Metadata publication times and camera image overlays can help distinguish an unchanged source image from a local display issue. Missing observations are not filled in. Wait for a later poll before concluding recovery failed; HTTP 429 responses can delay retries beyond the nominal interval.

Include version numbers, the affected entity type, relevant timestamps and the error text when reporting a problem. Remove credentials, tokens, private hostnames and personal location details from logs or screenshots. No diagnostics download is implemented yet.

## Updates and removal

For a later reviewed revision, use HACS's download/redownload or update control, restart HA, then refresh the browser. An app can retain stale frontend translations after restarting HA; compare with a fresh browser window if needed. Record which source revision you tested: without releases, the default-branch revision is the available package. The current manifest version is 0.6.1; a default-branch development update may require redownload rather than an update notification. Confirm selections and registry identities survive the restart. The categorized picker uses unchanged saved source IDs; actual HACS upgrade testing remains the user installation check.

To remove the integration, remove its parent entry from **Devices & services**, remove the downloaded package through HACS, and restart HA. Removing an individual station/camera subentry keeps the parent and other sources. Export anything you want to retain before removing the parent; this guide does not ask the development agent to perform removal on your instance.

## Local package verification

```bash
scripts/package
scripts/smoke-ui
```

The local archive is `.tools/packages/vegvesen-0.6.1.zip`, with an accompanying SHA256 file. It contains only `custom_components/vegvesen/` runtime files, including native-flow translations, brand images, the original MIT license and the data-attribution notice. It excludes environments, developer tools, tests, API fixtures and conversation exports. Fixed ZIP timestamps and permissions make repeated builds from the same files deterministic in the pinned environment.

The smoke runner extracts this package into a disposable HA configuration, then selects sources through the UI and verifies temperature, observation time and camera display. This proves the installed files work independently of a development source-tree link. It is not an actual HACS download test. The archive is a local review artifact; `hacs.json` still uses the ordinary repository layout, without ZIP-release mode.
