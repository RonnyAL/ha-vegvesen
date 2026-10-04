# Public fixture provenance

`weather_sample.json` was retrieved on 2026-10-03 from:

```text
https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/collections/datex_3_1:WeatherSimple_v2/items?f=application/json&limit=3
```

Data provided by Statens vegvesen. The official [weather dataset catalogue](https://dataut.vegvesen.no/nb/dataservice/vaerdata-malinger-api) identifies Norsk lisens for offentlige data (NLOD). These coordinates identify public road stations.

The captured response is retained unchanged, including pagination metadata and the `-39.6` air-temperature reading at source `1629004`. Tests build synthetic page counts, continuation links, omissions, zero/null values, and failures around copies of these features. They never contact the live API; source observations are not corrected. Timestamps describe the captured observations, not permanently fresh data.

## CCTV fixtures

`camera_sample.json` was retrieved unchanged on 2026-10-03 from:

```text
https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/collections/datex_3_1:CctvSimple_v2/items?f=application/json&limit=3
```

`camera.jpg` was retrieved on the same date from `https://kamera.atlas.vegvesen.no/api/images/3000047_2`. It is an unmodified public road-camera JPEG used for mocked HTTP responses. Neither its file time nor the catalogue publication time is claimed as its capture time.

Data provided by Statens vegvesen. The official [CCTV dataset catalogue](https://dataut.vegvesen.no/en/dataset/webkamera) identifies NLOD licensing. The JSON includes two available cameras and one reported camera fault. Tests construct synthetic failures, null status, and pagination around copies of these records; image bytes stay unchanged.

## Administrative geography fixtures

`geography_counties.json` and `geography_point.json` were retrieved unchanged
on 2026-10-03 from Kartverket's documented public endpoints:

```text
https://api.kartverket.no/kommuneinfo/v1/fylkerkommuner?utkoordsys=4326
https://api.kartverket.no/kommuneinfo/v1/punkt?nord=62.379288&ost=5.6275234&koordsys=4326
```

The point is the public Rundebrua source camera, not a personal location.
Administrative geography: [© Kartverket](https://www.kartverket.no/),
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), subject to
[Kartverket's terms](https://www.kartverket.no/api-og-data/vilkar-for-bruk).
Parsing tests use the complete directory; HTTP tests use a compact subset of
unchanged county records and synthetic point responses to exercise failures,
recovery and overlapping bounding boxes. No tests query live services.

## Routes and road-condition forecasts

`route_sample.json` was captured on 2026-10-04 from the documented public
`Route/best` endpoint, with `Stops=10.395,63.43;9.846,63.305`, both coordinate
systems set to `EPSG_4326`, `ReturnFields=Geometry` and `Lang=Norwegian`.
This example connects the public town centres of Trondheim and Orkanger.
The JSON was parsed and reserialized; response fields are retained.
Transient routing IDs must not be used as saved-route identity.

`road_forecast_sample.json` contains three source features selected from a
complete, spatially and temporally filtered `vegvar_1_0:vv_road_prognosis_V2`
snapshot on the same date. Feature geometries and properties are unchanged;
the small FeatureCollection envelope/counts are constructed and API feature
IDs are omitted. Tests construct pagination and missing, unusual or future
category values around copies, without contacting public services.

Data provided by Statens vegvesen. [Endpoint, field and licence research](../../docs/route-forecasts.md).
