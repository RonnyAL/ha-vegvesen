# Fylke and kommune source selection (0.2.0)

Both weather-station and camera setup now begin with **Fylke / County**.
Choose a county and submit, choose a kommune or **All municipalities** and
submit, then select a source from the smaller list. Each form retains the
region controls: leave the source empty, change a region and submit to browse
elsewhere. **All Norway / Hele Norge** opens the original nationwide list.
The same picker works for the first source and subsequent subentries.

Existing devices, entities and subentries need no migration. Only the chosen
source ID is saved; fylke/kommune choices are temporary discovery filters.
Each additional source can be selected anywhere in Norway. Polling and source
values are unchanged, and no geographic setting restricts the parent entry or
future independent area/route monitors.

## Verified geography source

Live `WeatherSimple_v2` responses include a `COUNTY` string but no kommune.
`CctvSimple_v2` responses include neither administrative field. To give both
pickers consistent current classifications, administrative metadata comes from
[Kartverket's documented API](https://api.kartverket.no/kommuneinfo/v1/).
The API describes the older `ws.geonorge.no` URL as a proxy and recommends the
`api.kartverket.no` endpoint, which was verified directly on 2026-10-03.

- `GET /fylkerkommuner?utkoordsys=4326` returns the complete county/municipality
  directory, names, string codes (including leading zeroes) and bounding boxes.
- `GET /punkt?nord=<latitude>&ost=<longitude>&koordsys=4326` returns the county
  and municipality containing a public source coordinate. Actual responses
  classify Rundebrua as Herøy (1515), Møre og Romsdal (15), and Våvatnet as
  Orkland (5059), Trøndelag (50). A point outside Norway returned HTTP 404.
- No authentication is required, according to the API's OpenAPI description.

Bounding boxes only reduce the candidates that need a point lookup. They do
not establish membership: overlapping boxes cannot incorrectly put a source
in the chosen county or kommune. Direction-specific camera IDs remain intact.
Names and administrative codes are taken from Kartverket rather than guessed
from source names, road numbers or source IDs.

Administrative geography: [© Kartverket](https://www.kartverket.no/), licensed
under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) and
[Kartverket's terms](https://www.kartverket.no/api-og-data/vilkar-for-bruk).
Attribution appears in the picker and installed `NOTICE.md`. No numerical
measurements, camera statuses or source coordinates are corrected by this step.

## Failures and request behavior

The directory and exact-coordinate lookup cache last only for the current
flow. Equal coordinates, including multiple camera directions, share a lookup.
At most four point requests run concurrently; the entire filter has a
30-second timeout. Cancellation stops outstanding lookup tasks. These requests
never run from the weather or camera polling coordinators.

Any failed or malformed candidate lookup rejects the filter; a partially
classified source list is never presented as complete. The user can retry,
choose another region, or select **All Norway** even while Kartverket is down.
An empty region shows an explicit message and keeps its region controls.
Sources without coordinates or recognized administrative membership remain
available in the nationwide list. A large county can require more lookups than
a municipality; municipality selection reduces the requests.

## Updating through HACS

Download/update or redownload the custom repository's latest default branch,
then restart HA. Confirm the integration shows **0.2.0**. Existing configured
sources keep working; use **Add weather station** or **Add road camera** to
try the new picker. No default-list submission or household deployment was
performed by the development agent.
