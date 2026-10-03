# Public fixture provenance

`weather_sample.json` was retrieved on 2026-10-03 from:

```text
https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/collections/datex_3_1:WeatherSimple_v2/items?f=application/json&limit=3
```

Data provided by Statens vegvesen. The official [weather dataset catalogue](https://dataut.vegvesen.no/nb/dataservice/vaerdata-malinger-api) identifies Norsk lisens for offentlige data (NLOD). These are public road-station locations, not household coordinates or user selections.

The captured response is retained unchanged, including pagination metadata and the `-39.6` air-temperature reading at source `1629004`. Tests build synthetic page counts, continuation links, omissions, zero/null values, and failures around copies of these features. They never contact the live API; source observations are not corrected. Timestamps describe the captured observations, not permanently fresh data.

## CCTV fixtures

`camera_sample.json` was retrieved unchanged on 2026-10-03 from:

```text
https://ogckart-sn1.atlas.vegvesen.no/ogc/features/v1/collections/datex_3_1:CctvSimple_v2/items?f=application/json&limit=3
```

`camera.jpg` was retrieved on the same date from `https://kamera.atlas.vegvesen.no/api/images/3000047_2`. It is an unmodified public road-camera JPEG used for mocked HTTP responses. Neither its file time nor the catalogue publication time is claimed as its capture time.

Data provided by Statens vegvesen. The official [CCTV dataset catalogue](https://dataut.vegvesen.no/en/dataset/webkamera) identifies NLOD licensing. The JSON includes two available cameras and one reported camera fault. Tests construct synthetic failures, null status, and pagination around copies of these records; image bytes stay unchanged.
