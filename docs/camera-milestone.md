# Camera milestone

## Verified API behavior

The public [OGC catalogue](https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/collections) exposes `datex_3_1:CctvSimple_v2`. Requests to its `items` endpoint with `f=application/json` worked without credentials on 2026-10-03. `filter-lang=cql2-text` with `CAMERA_ID IN ('3000047_2',...)` was verified using multiple pages and an empty terminal page. The integration shares the weather client's strict, atomic pagination implementation.

| Source property | Meaning and use |
| --- | --- |
| `CAMERA_ID` | Exact stable source ID, including direction suffix; device/entity namespace `camera:<id>` |
| `DESCRIPTION`, `ORIENTATION_DESCRIPTION` | Readable selection/device labels; do not determine identity |
| `STILL_IMAGE_URL`, `STILL_IMAGE_FORMAT` | Source still-image endpoint and format; currently observed JPEGs |
| `STILL_IMAGE_SERVICE_LEVEL`, `STATUS_STILL_IMAGE_SERVICE_LEVEL` | Source service-level integers; preserved unchanged |
| `STATUS_STILL_IMAGE_AVAILABILITY` | Raw status exposed by a sensor, including unknown future strings and null |
| `PUBLICATION_TIME`, `LAST_UPDATE_TIME` | Offset-aware metadata timestamps; not presented as image capture time |
| Point geometry, `ROAD_NUMBER` | Longitude/latitude and road metadata; no parent-wide geographic restriction |

GeoServer feature IDs and `PUB_ID` change with publications and are not identities. `CAMERA_ID` is not shortened to the site prefix, since directional images are distinct physical sources. Optional metadata and timestamps remain null when missing.

The official [WFS/WMS specification](https://git.vegvesen.no/projects/DATEX2/repos/datex2-spesifications/browse/3.1/wfs-wms) documents service level 1 as available and 0 as unavailable. Actual responses supplied the `videoOrImagesAvailable` status and fault statuses such as `videoOrImagesUnavailableDueToCameraFault`. A JPEG is requested only when both levels are 1, status explicitly reports availability, format is `jpeg`, and a URL is present. Unknown/null status is not treated as confirmed availability; its exact source value remains visible in the status sensor.

Observed URLs use `https://kamera.atlas.vegvesen.no/api/images/<camera-id>`. Actual GET responses returned JPEG bytes with `Content-Type: image/jpeg`, without ETag, Last-Modified, or Cache-Control headers. A conditional request in the investigation still returned 200. No unsupported conditional cache contract is assumed. The current client accepts that observed HTTPS host/path and rejects redirects/other endpoints explicitly; a new source endpoint would require verification before support is expanded.

The [official CCTV dataset catalogue](https://dataut.vegvesen.no/en/dataset/webkamera) identifies NLOD licensing and explains that update frequency varies by camera and communications. The [DATEX publication documentation](https://www.vegvesen.no/en/fag/technology/open-data/a-selection-of-open-data/what-is-datex/publications/) requires attribution. Data is attributed to Statens vegvesen in entities, documentation, and fixtures. The separate XML service requires registration; the tested OGC and image endpoints did not.

## Implemented behavior

The singleton parent can start with either a station or camera. Further `camera` and `weather_station` subentries are added under that parent, with duplicate rejection within each source type. Source ownership remains one physical subentry/device; overlapping future monitors must reference it, as described in the [weather ownership notes](weather-milestone.md).

A camera subentry owns one still-camera entity and one **Source availability** sensor on the same device. The status sensor is necessary because HA hides extra attributes on unavailable camera entities. It preserves fault/unknown status and metadata when image retrieval fails. Null status is unknown; absent records or failed metadata snapshots make both entities unavailable. Metadata timestamps and image-request errors appear as attributes; no image capture timestamp, stream, camera controls, or risk score is invented.

The camera coordinator polls only selected camera IDs and their supported, available stills at a nominal one-minute interval. This interval is an integration choice, not a verified uniform publication cadence. A shared semaphore limits concurrent image requests to four. JPEGs are cached in memory; frontend requests return the cached source bytes without additional source requests. Collection refreshes have a 30-second deadline, and individual image requests have a ten-second deadline. Transport validation requires a JPEG content type and nonempty JPEG start/end markers; it does not fully decode or assess image quality. HA may scale images for display.

All metadata pages must complete before any new still request starts. A failed/incomplete metadata refresh retains the old internal snapshot and makes the CCTV family unavailable; cached old bytes are not served while unavailable. Image failures are per camera: that camera's current snapshot has no usable image, while other cameras and the source-status sensors continue working. Images recover on later polling. Image 429 responses defer only that source's image retries until Retry-After expires, rounded up to the next poll. Metadata 429 responses delay the CCTV coordinator through HA's Retry-After support. Weather's polling and availability are independent.

At setup/reload, selected source families refresh independently. If one metadata family succeeds, its entities load while the failed family starts unavailable and retries through its coordinator. If every selected metadata family fails, HA retries parent setup. An entry with no selections does no source I/O. Add/remove changes reload the parent; identifiers remain stable across source renaming/republishing. Unloading shuts down coordinator listeners/timers and cancels in-flight scheduled image requests without closing HA's shared session.

## Validation and limitations

The locked test target remains CPython 3.14.8 / HA 2026.9.4 / pytest-homeassistant-custom-component 0.13.367. The environment adds the exact `PyTurboJPEG==1.8.3` requirement from that HA camera manifest for tests; its source build uses a pinned setuptools constraint. No native host library or service is installed or changed. Tests request unscaled cached JPEGs; native display scaling is outside this milestone.

The integration declares `camera` in `after_dependencies`, so HA installs that built-in platform's own requirements before importing camera code, without duplicating its runtime package pins in this integration's manifest.

HA's 2025.12.0 camera source already provides the `Camera` initializer and `async_camera_image(width, height)` interface used here; no newer runtime API was introduced. The supported HA minimum stays 2025.12.0 and now passes the complete 118-test suite, including camera behavior. Local/CI checks include `scripts/check-minimum`, `scripts/validate-hassfest`, and `scripts/validate-hacs`; see [validation details](validation.md).

No numerical quota, image capture-time field, or atomic multi-page snapshot guarantee was verified. A successful GET cannot establish freshness; no stale-image threshold is invented. The integration currently supports still JPEGs at the verified image endpoint, not video streaming. HACS/Hassfest execution, branding, and isolated UI testing remain release preparation tasks.
