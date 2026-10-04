# Native source selection

Weather stations and cameras use a native Home Assistant menu as an editable
selection overview. It shows the chosen county, municipality and source count.
Choose/change actions open a native form; **Done** returns to the overview.
The source form accepts multiple source IDs and renders readable selected labels.
**Add** appears only when sources are selected. There are no navigation sentinels
inside the source or region dropdowns and no custom frontend module.

Only populated regions are offered; there is no “Hele Norge” choice. Changing
county clears municipality and sources. Changing municipality clears sources.
Resubmitting an unchanged region preserves its dependants. Closing the flow
before Add saves nothing. Each batch is from one municipality; subsequent batches
can be anywhere in Norway. The parent has no geographic restriction.

## Verified HA conventions and lifecycle

The [documented native menu](https://developers.home-assistant.io/docs/data_entry_flow_index/#show-menu)
selects defined flow steps. Native forms send data on submission, not whenever
a local field changes. They do not expose a configurable Back button. The overview
therefore supplies explicit editing actions between forms, without claiming a
Back button inside an editor. The [select selector](https://www.home-assistant.io/docs/blueprint/selectors/#select-selector)
supports multiple selections with separate machine values and readable labels.

All four parent/subentry paths share this behavior. Initial parent creation uses
the public flow result's `subentries` list. An existing parent uses the public
`async_add_subentry` API for additional selections and the normal subentry flow
result for the final source. Every requested source is checked by one complete,
filtered live snapshot before any is saved. Duplicate checking runs both before
and after network I/O. Saving the validated batch is synchronous, so overlapping
flows cannot insert a duplicate between the final check and persistence.

HA eagerly runs update listeners. The listener yields one event-loop turn before
reloading, allowing a synchronous batch to finish and coalescing its callbacks.
If another selection arrives during reload I/O, membership and saved data/title
are checked again and the entry reloads to include it. Old coordinators are shut down. Weather/camera
polling remains independent and physical source identities are unchanged.
No migration is needed. Future monitor ownership and deduplication remain
architecture considerations; no monitor framework is introduced.

English and Bokmål have matching titles, field labels and menu actions. Setup
contains only the selection summary and necessary labels/errors. Attribution
remains in the README and installed `NOTICE.md`. An open frontend can keep older
translations across a backend restart; refresh it after updating. This release
cannot force the companion app to discard its cached frontend resources.

Both supported HA versions test native serialization, filtering, draft editing,
batch creation, failed/incomplete pagination, duplicate races and reload lifecycle.
The primary frontend also has a real browser smoke test of an extracted runtime
package. A minimum-version frontend test remains unperformed.

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
All chosen sources are checked again with a filtered live request at Add.
There are no discovery polling tasks, persistent runtime cache files or changes
to entity polling.

## Updating through HACS

Update or redownload the custom repository's latest default branch, restart HA,
refresh the frontend, and confirm the installed version matches the download. Existing
selections keep working. Use **Add weather stations** or **Add road cameras**
to try the editable overview.
