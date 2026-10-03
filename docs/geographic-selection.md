# Native source selection (0.4.2)

Weather stations and cameras use three native Home Assistant forms: county,
municipality, source. The first two use HA's **Next** action; the final form
uses **Submit**. Fields are initially blank and use built-in dropdown selectors.
County/municipality options are derived from actual sources of the requested
family, so there are no empty regions or “Hele Norge” option. The selected
source displays its name and ID in the closed dropdown.

The municipality dropdown includes **Change county**, and the source dropdown
includes **Change municipality**. Submitting either returns to the previous
form, retaining its selected value. Resubmitting the same county retains the
municipality; changing county clears it. A changed municipality refilters the
source list. Navigation makes no additional API requests and saves no data. Only the
final source ID is stored. Existing devices, entities and subentries need no
migration; source polling and values are unchanged. Additional selections can
be anywhere in Norway, with no parent-wide restriction or dependency on future
area/route monitors.

## Verified HA conventions

The [documented multi-step flow](https://developers.home-assistant.io/docs/data_entry_flow_index/#multi-step-flows)
advances when the current form is submitted. HA's stock form does not send
local select changes to the integration or reactively replace other field
schemas. Native navigation menus choose among defined flow steps, rather than
providing a data-bearing hierarchical browser. Stock forms expose no configurable
Back button; navigation choices use the built-in dropdown and submit action.
They are handled before source validation and cannot create a source entry. The [choose selector](https://www.home-assistant.io/docs/blueprint/selectors/#choose-selector)
switches between selector types; current [core validation](https://github.com/home-assistant/core/blob/2026.9.4/homeassistant/helpers/selector.py)
explicitly rejects nested choose selectors, and it is absent from the minimum
2025.12.0 test target.

The native wizard avoids custom selector rendering, extra modules, static asset
registration and first-install browser reloads. The 0.4.0 custom selector could
leave an empty custom element when its module was unavailable: its successful
isolated test did not establish reliability on other installations. There is
no integration JavaScript in 0.4.2. Setup text contains only titles and labels;
source attribution is retained in the README and installed `NOTICE.md`.

HA merges new translation resources over its existing browser resources. Deleted
keys can therefore retain old descriptions across a backend reconnect. Explicit
empty description and field-description strings overwrite the previous setup
instructions and attribution, including their removed URL placeholder. English
and Bokmål include matching labels for every parent/subentry step. After a HACS
update, restart HA and refresh the browser or reopen the companion app.

Both supported backend targets test real native schema serialization, all four
parent/subentry source paths, filtering, rejection of invalid or out-of-region
choices, failure/retry and saving only source IDs. The primary frontend has a
live first-use browser test with no close/reload workaround. A minimum-version
live browser test remains unperformed.

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
Attribution appears in the README and installed `NOTICE.md`. Numerical
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
refresh the frontend, and confirm version **0.4.2**. Existing
selections keep working. Use **Add weather station** or **Add road camera**
to try the native hierarchy.
