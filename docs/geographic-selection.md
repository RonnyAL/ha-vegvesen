# Searchable source selection (0.3.0)

Weather stations and cameras use one native Home Assistant searchable picker.
Type a fylke, kommune, source name or source ID, select a listed result, then
submit once. Labels have the form **Trøndelag / Orkland / Fv 714 Våvatnet
(1629006)**. Only actual records from the requested source catalogue appear;
there are no county or municipality choices that lead to an empty list.
The same form works for the first source and subsequent subentries.

Home Assistant's [standard data-entry forms](https://developers.home-assistant.io/docs/data_entry_flow_index/)
do not provide reactive dependent dropdowns without a submission. This uses
its [select selector](https://www.home-assistant.io/docs/blueprint/selectors/#select-selector)
instead of introducing a custom frontend. The tested frontend uses its searchable,
virtualized picker for `custom_value` selectors; the flow explicitly rejects
unknown text. Choose a listed result rather than the frontend's generic
**Add custom item** option. This behavior is covered by flow tests and a real
frontend smoke test. [Official frontend implementation](https://github.com/home-assistant/frontend/blob/20260826.7/src/components/ha-selector/ha-selector-select.ts).

Existing devices, entities and subentries need no migration. Only the chosen
source ID is saved. Each additional source can be selected anywhere in Norway.
Polling and source values are unchanged; there is no parent-wide geographic
restriction or dependency on future area/route monitors.

## Verified geography source

Live `WeatherSimple_v2` responses include a `COUNTY` string but no kommune.
`CctvSimple_v2` responses include neither administrative field. Administrative
labels for both source families come from [Kartverket's documented API](https://api.kartverket.no/kommuneinfo/v1/).
The API recommends `api.kartverket.no` rather than the older `ws.geonorge.no`
proxy. Endpoints were verified directly on 2026-10-03:

- `GET /fylkerkommuner?utkoordsys=4326` supplies county/municipality names,
  string codes (including leading zeroes) and bounding boxes.
- `GET /punkt?nord=<latitude>&ost=<longitude>&koordsys=4326` gives the exact
  administrative membership of a public source coordinate. Rundebrua is
  Herøy (1515), Møre og Romsdal (15); Våvatnet is Orkland (5059), Trøndelag (50).
  A point outside Norway returned HTTP 404.
- The OpenAPI description specifies no authentication.

The bundled `source_geography.json` was generated from complete live Statens
vegvesen catalogues and Kartverket point responses. It contains all 468 weather
stations and 896 direction-specific cameras in the 2026-10-03 snapshot.
The 1,364 records required 907 distinct coordinate lookups; equal coordinates
share a request, with at most four concurrent requests. Names and codes are
supplied by Kartverket, not inferred from source IDs, names or bounding boxes.
The generation script replaces the file only after all requests succeed.
See [regeneration instructions](development.md#updating-source-geography).

Administrative geography: [© Kartverket](https://www.kartverket.no/),
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), under
[Kartverket's terms](https://www.kartverket.no/api-og-data/vilkar-for-bruk).
Attribution appears in the picker and installed `NOTICE.md`. Numerical
measurements, camera statuses and coordinates remain source values.

## Discovery, failures and freshness

Setup reads the bundled index once through HA's executor. No Kartverket
network request runs during setup or polling. Administrative names are a
release snapshot; boundary or name changes require regeneration. Geographic
prefixes require an exact source-ID and coordinate match. New, moved,
coordinate-free or unclassified sources remain selectable by name and ID.
An unavailable or malformed index falls back to that same unclassified list.

Source catalogues are live, paginated and cached independently for weather and
cameras for 15 minutes per HA instance. The first or expired lookup still needs
a complete network response. Concurrent flows share one fetch; each gets its
own dictionary copy. Failed, cancelled, malformed or incomplete pagination
cannot publish a partial catalogue or replace the previous successful cache.
An expired cache is not served as a successful refresh after a request failure.
The form reports the failure for retry. Empty responses are not reused.
The chosen source is checked again with a filtered live request at submission.
There are no discovery polling tasks, persistent runtime cache files or changes
to entity polling.

## Updating through HACS

Update or redownload the custom repository's latest default branch, restart HA,
and confirm version **0.3.0**. Existing selections keep working. Use
**Add weather station** or **Add road camera** to try the new picker.
