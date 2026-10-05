# Test through a HACS custom repository

The public repository is available through HACS **Custom repositories**. It is not listed in HACS's default catalogue. Follow the [README installation instructions](../README.md#install-with-hacs); select a numbered GitHub release for versioned updates; `main` remains available for development testing. See the official [custom repository instructions](https://www.hacs.xyz/docs/faq/custom_repositories/).

Use Home Assistant **2025.12.0 or newer** and HACS **2.0.5 or newer**. The automated HA targets are **2025.12.0**, **2026.9.4** and **2026.10.0b0**. HA uses its own managed Python; repository development tools are not needed on the installation host.

## First test session

Record your HA version and installed integration version. Public station/camera IDs help reproduce problems, but your selections and route coordinates can reveal locations of interest; omit them from public reports if needed.

| Check | Expected result |
| --- | --- |
| Source picker | County → municipality → source checkboxes; save several sources together; populated regions only; Norwegian municipality names and readable source IDs |
| One station | One physical device, an air-temperature sensor and an observation-time sensor |
| One camera | One direction-specific device, a still camera and a raw source-availability sensor |
| One route | Choose existing HA zones or map endpoints; leave the name blank to derive it from zones/the road proposal; confirm the map preview and save one route device with seven enabled forecast sensors and four optional count sensors |
| Route map card | After refreshing the frontend, select the card and saved route by name; pan/zoom, inspect segments and choose map appearance without manual resource registration |
| Entity presentation | Dedicated road/slipperiness/count/camera-status icons; zone-based IDs for new automatically named routes; existing IDs retained |
| Additional selections | All sources/routes under one parent; an already selected physical source ID cannot be added twice |
| Source null or missing observation | Unknown measurement; zero and unusual numeric values preserved |
| Normal refreshes | Weather nominally every ten minutes; camera metadata/still every minute; routes just after the hour and half-hour |
| Route hour rollover | With 1 hour ahead selected, a refresh just after 15:00 selects 16:00; condition/temperature values can remain unchanged |
| Route zone changes | Saved geometry remains in use; edit settings or recalculate to resolve a moved zone and calculate a new road route |
| Independent failures | Ordinary route failures are isolated; server rate limits can pause routes sharing the forecast endpoint |
| Camera detail dialog | A source still is displayed; metadata publication/update times are not claimed as image capture times |
| Restart or reconfigure | Selections retained and device/entity identities stable; fresh data fetched on reload |
| Remove one subentry | Its entities and unowned device removed; other selections remain configured |

There is no API credential or integration-wide location setting. Routes have independent geometry/corridors; area monitors and automatic station/camera ownership by monitors are not implemented. UI labels have English and Norwegian Bokmål translations.

Observe ordinary source failures if they occur; testing does not require disrupting the installation host's network or services. Request failures produce unavailable entities and recover on successful polls. A failed JPEG affects only that camera's image; its raw status sensor can still expose source metadata. Incomplete pagination fails the whole affected refresh. A missing station/camera in a complete snapshot is unavailable individually. Empty route matches give zero segments and unknown forecast states. These paths are covered by mocked tests.

## Troubleshooting

If HA cannot find the integration after download, confirm the installed path is `<HA config>/custom_components/vegvesen/manifest.json`, restart HA, and check the logs.

For blank labels or old setup text, compare with a fresh browser window. The companion app can retain translations across an HA restart; use **Reset frontend cache** in its settings. Reinstalling configured sources is unnecessary.

If a source is unavailable, inspect its status and the HA logs. Metadata publication times and camera image overlays can help distinguish an unchanged source image from a local display issue. Missing values are not filled in. HTTP 429 retry delays take precedence over the usual schedule. A successful refresh can leave readings unchanged; forecast valid time describes the forecast hour, not publication time.

Include version numbers, affected entity type, relevant timestamps and error text when reporting a problem. Remove credentials, tokens, private hostnames and personal location details. No integration diagnostics download is implemented yet.

## Updates and removal

Use HACS's update control or redownload a numbered release, restart Home Assistant (not the host), then refresh the frontend. For an existing `main` installation, use **Update information**, then **Redownload** and select **0.8.1** if the release is not offered automatically. The first transition may show a commit-to-version change; subsequent release updates show version numbers. Integration reload alone does not load upgraded Python code. Confirm the installed version and that selections/identities survive the restart. See [release and lifecycle details](releases.md).

To remove everything, remove the parent integration entry from **Devices & services**, remove the downloaded package through HACS, and restart HA. Removing an individual station, camera or route subentry keeps the parent and other selections.

## Local package verification

For contributors, these optional commands build a runtime archive and exercise it in a disposable HA instance:

```bash
scripts/package
scripts/smoke-ui
```

The archive is `.tools/packages/vegvesen-<version>.zip`, with an accompanying SHA256 file. It contains only `custom_components/vegvesen/` runtime files, including translations, brand images, the original MIT license and data attribution. It excludes environments, developer tools, tests, fixtures and conversation exports. Fixed ZIP timestamps and permissions make repeated builds deterministic in the pinned environment.

The smoke runner extracts the package, configures public stations/cameras and a route through the real frontend, and verifies their states and a camera image. It checks installed files independently of a source-tree link; it is not an actual HACS download test. See [validation evidence and limitations](validation.md). HACS continues to use the ordinary repository layout, without ZIP-release mode.
