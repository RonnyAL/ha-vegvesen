# Dependent source selection (0.4.0)

Weather stations and cameras use three dropdowns in the Home Assistant setup
form: county, municipality, source. The latter two start disabled. Choosing a
county enables its municipality list; choosing a municipality enables its
source list. Changing a county clears both child choices; changing a
municipality clears the source. There is one final submission. Counties and
municipalities are derived from actual sources of the requested family, so
there are no empty regions or “Hele Norge” option. Names and IDs remain readable
in the closed source dropdown.

Existing devices, entities and subentries need no migration. Only the chosen
source ID is saved. Each additional source can be selected anywhere in Norway.
Polling and source values are unchanged; there is no parent-wide geographic
restriction or dependency on future area/route monitors.

## Frontend implementation and loading

HA's [standard data-entry forms](https://developers.home-assistant.io/docs/data_entry_flow_index/)
do not update dependent field schemas on local selections. A small bundled
JavaScript module provides an integration-owned selector containing three
native HTML selects. It does not replace HA widgets or patch frontend code.
Changes filter the form's catalogue locally and emit a scalar source ID through
HA's existing selector event contract. There are no runtime frontend dependencies,
external scripts, network calls on dropdown changes, or polling timers.

The integration uses HA's extra-module registration and asynchronous static
paths to serve a versioned local URL. HA's [frontend module loading](https://www.home-assistant.io/integrations/frontend/#loading-extra-javascript)
occurs on page load. Existing entries register it at integration startup:
restart HA after updating and reload the browser/app page. On first-ever
installation, open **Add integration → Statens vegvesen** once, close the dialog,
reload the page, then reopen setup. The setup text and README explain this step.

Custom selector rendering relies on the frontend's dynamic tag and event
contract, which is an implementation detail rather than a documented extension
API. The official [20260826.7 renderer](https://github.com/home-assistant/frontend/blob/20260826.7/src/components/ha-selector/ha-selector.ts)
and [20251203.0 renderer](https://github.com/home-assistant/frontend/blob/20251203.0/src/components/ha-selector/ha-selector.ts)
were checked. Backend serialization is tested on both HA targets, with an
explicit blank default to avoid native default inference for the custom type.
A real browser smoke test exercises the current frontend. The minimum
frontend has not had the same live browser test; future HA frontend changes
may require maintaining this bridge.

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
release snapshot; boundary or name changes require regeneration. Membership
requires an exact source-ID and coordinate match. New, moved, coordinate-free
or unclassified sources remain selectable under **Unknown county → Unknown
municipality**. An unavailable or malformed index puts all live sources in
those explicit buckets rather than assigning guessed geography.

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
reload the Home Assistant page, and confirm version **0.4.0**. Existing
selections keep working. Use **Add weather station** or **Add road camera**
to try the three dropdowns.
