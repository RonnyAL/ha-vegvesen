# Statens vegvesen for Home Assistant

Road weather, camera images and route forecasts for Norway, in Home Assistant.
Choose weather stations and cameras, save your regular routes, and explore
forecast conditions on an interactive map.

An independent community integration using public data from Statens vegvesen.
No API key or Statens vegvesen account is required. Configuration and the map
card are available in English and Norwegian Bokmål.

| Feature               | What you get                                                        | Refresh interval                     |
| --------------------- | ------------------------------------------------------------------- | ------------------------------------ |
| Weather stations      | Air temperature and observation time                                | 10 minutes                           |
| Road cameras          | Still images and source availability                                | 1 minute                             |
| Route forecasts       | Road conditions, slipperiness, road temperatures and segment counts | Just after each hour and half-hour   |
| Interactive route map | Color-coded forecasts, segment details, pan and zoom                | Follows the route's forecast updates |

[Installation](#install-with-hacs) · [Stations and cameras](#choose-stations-and-cameras) · [Routes](#route-forecasts-føreforhold) · [Map card](#route-maps) · [Support](#troubleshooting-and-support)

## Requirements

- Home Assistant **2025.12.0 or newer**.
- [HACS](https://www.hacs.xyz/docs/use/) **2.0.5 or newer**, if installing through HACS.
- Internet access for source data and map backgrounds.
- A browser or companion app with **WebGL 2** support for the interactive map.

## Install with HACS

Add this integration as a [HACS custom repository](https://www.hacs.xyz/docs/faq/custom_repositories/):

1. Open **HACS → menu → Custom repositories**.
2. Add `https://github.com/RonnyAL/ha-vegvesen` with type **Integration**.
3. Find **Statens vegvesen** and download the latest stable release.
4. Restart Home Assistant.
5. Open **Settings → Devices & services → Add integration** and search for **Statens vegvesen**.

Choose weather stations, road cameras or a route forecast to get started. Add
more sources and routes from the same integration whenever you like.

<details>
<summary>Manual installation</summary>

Download the source archive from the [latest release](https://github.com/RonnyAL/ha-vegvesen/releases/latest).
Copy its `custom_components/vegvesen` folder into your Home Assistant
configuration's `custom_components` folder. Restart Home Assistant, then add the
integration through **Settings → Devices & services**.

</details>

## Choose stations and cameras

1. Choose **Weather station** or **Road camera** during setup, or use
   **Add weather stations** / **Add road cameras** on the integration.
2. Select a county (_fylke_), then a municipality (_kommune_).
3. Select one or more sources and save.

Only counties and municipalities with sources of the selected type are listed.
Sources show their names, camera directions where available, and source IDs.
Municipality names use Norwegian names from Kartverket.

Each selection covers one municipality. Repeat the process to add sources
elsewhere in Norway; previous selections do not restrict later ones. The same
source cannot be added twice. Discovery lists are cached for up to 15 minutes.

## Using the entities

Each station, camera and route appears as a device in **Settings → Devices &
services**. Add its entities to dashboards or use them in automations.

- **Air temperature** is the station's measured value, displayed in your preferred temperature unit.
- **Observation time** is when the reading was measured, which can differ from the last refresh.
- **Road camera** shows the latest retrieved still image. The image may stay unchanged between refreshes.
- **Source availability** reports the camera status supplied by Statens vegvesen.

Source values are preserved, including unusual readings. Missing readings are
**unknown**; request failures make affected entities **unavailable** until a
successful refresh. Weather, cameras and routes recover independently.

Entity IDs are generated from device and sensor names. Routes named after zones
use those names too. Existing IDs remain stable across updates and route renames;
custom names and icons are retained. You can edit entity IDs in Home Assistant.

## Route forecasts (føreforhold)

Choose **Route forecast** during setup or **Add route** on the integration.

1. Pick a start and destination using existing Home Assistant zones or
   **Choose on map**. You can mix the two. Give the route a name, or let the
   integration name it from the zones and road proposal.
2. Set the corridor and forecast hours ahead. Defaults are **100 metres** on
   either side of the route and **0 hours** ahead.
3. Continue and set any map points. Review the calculated route on the preview
   map; choose another proposal if the routing service offers alternatives.
4. Select **Save route**. Settings can be edited before saving or reconfigured later.

Each route has seven enabled sensors:

| Sensor                             | Meaning                                                                      |
| ---------------------------------- | ---------------------------------------------------------------------------- |
| Road condition                     | Source conditions across matching segments; **Mixed** when categories differ |
| Slipperiness                       | Source slipperiness categories across matching segments                      |
| Highest forecast slipperiness      | Highest recognized source grade: low, medium or high                         |
| Minimum / maximum road temperature | Lowest and highest available forecast road-surface temperatures              |
| Forecast valid time                | The hour the forecast applies to                                             |
| Forecast segments                  | Number of matching source segments, including those with missing values      |

Four optional sensors count segments with **ice/frost**, **snow cover**,
**drifting snow** and **high slipperiness**. Enable them on the route's device
page. Sensor attributes include category counts and missing-data counts.

### Understanding the forecast

With **0 hours ahead**, a refresh at 14:35 selects the forecast for 14:00.
With **1 hour ahead**, it selects 15:00. These are forecasts, including at
0 hours; measured observations come from weather stations. Refreshes run on
loading, then just after `:00` and `:30`. Values can remain unchanged after a
successful refresh, and the source may not yet have published a requested hour.

Condition and slipperiness summaries show **Incomplete data** when only some
segments have usable values, or **unknown** when none do. Highest slipperiness
still reports the highest known grade when other segments lack data. Missing
temperatures are omitted from the minimum and maximum. Failed or incomplete
requests make the route unavailable; partial results are never shown as a
complete refresh.

The corridor can include side roads, crossing roads and opposite carriageways.
It can be set from **1 to 2,000 metres**, in one-metre steps. A narrower corridor
can exclude nearby roads, but can also miss forecast segments where their
geometry differs from the calculated route. The default remains 100 metres.
Segment counts describe source records, not distance or a percentage of route
coverage. A low slipperiness grade or **No new precipitation** does not establish
safe conditions or complete coverage. The integration presents source forecasts
without creating its own road-risk score. Traffic incidents and closures are
not included.

Routes support two endpoints and remain independent of selected stations,
cameras and other routes. Moving a zone does not change a saved route: use
**Recalculate route** to update its geometry.

### Forecasts in automations

Use **Statens vegvesen: Get route forecasts** in **Developer tools → Actions**
or an automation, and select your route device. Set **Forecast time** to request
conditions for a particular hour, such as a planned departure. Leave it empty
to use the route's latest cached forecast without an extra source request.

The response includes condition counts, the highest known slipperiness grade,
minimum/maximum road temperatures and missing-data counts. Turn off **Include
segment data** for a compact response, or leave it on for individual segment
geometry and source properties. Use Home Assistant's response variable to build
notifications or further automation conditions.

Times select the containing UTC hour: in Norway, 07:45 requests 07:00. Times without
an explicit offset use Home Assistant's time zone. Requests can cover the current
hour through 24 hours ahead, but the source may not have published that hour.
An empty result means no matching forecast was returned. Request failures raise
an action error; partial responses are never returned as complete forecasts.

Requests for the same route and hour share a five-minute cache. Querying another
hour does not change the route's settings, sensors or map. See the
[morning briefing example](examples/route_forecast_briefing.yaml) and
[response reference](docs/forecast-action.md) to get started. In the example,
replace `YOUR_ROUTE_DEVICE_ID` with your route's device ID from the action editor,
and adjust the briefing and departure times.

## Route maps

During configuration, the preview shows **A** at the start and **B** at the
destination. After saving, use the interactive dashboard card to explore
conditions along the route.

### Interactive dashboard card

The **Statens vegvesen route map** card is included and loads automatically.
There are no JavaScript files or dashboard resources to install manually.

1. Configure a route in **Settings → Devices & services → Statens vegvesen**.
2. Refresh your browser or fully close and reopen the companion app.
3. Edit a dashboard and select **Add card → By card → Statens vegvesen route map**.
4. Select your route by name and save. A single saved route is selected automatically.

Pan and zoom, tap a colored segment for its forecast details, or expand the map
for a larger view. The controls on the left let you fit the whole route and open
the layers and legend panel when needed. Forecast time and missing-data counts
are available in that panel. Switch between **Road condition** and
**Slipperiness** while keeping the same position and zoom, or select a category
to highlight and fit its segments.
Missing and unrecognized data are shown explicitly. Forecast times use Home
Assistant's configured time zone.

In the layers panel, **Forecast valid time** defaults to **Automatic**, following
the route's configured forecast. Choose an hour or use the previous/next arrows
to compare forecasts while keeping your position and zoom. A small time button
and previous/next arrows stay visible when the panel is closed, so you can step
through hours directly on the map. Tap the time to reopen the selector or return
to Automatic. Your selection affects this card only and resets when the page reloads.

A selected hour stays fixed and refreshes every five minutes while the page is
visible. Requests share the automation action's cache. Unpublished hours show
**No forecast segments**; failed requests clear the forecast overlay and offer
**Retry**. Once the selected hour has passed, choose another hour or Automatic.
The selector covers the current hour through 24 hours ahead; availability varies.
Cameras and weather stations continue to show their latest images and measured
observations, independently of the forecast hour.

The card has no title by default. Its visual editor offers an optional title and
these **Appearance** settings:

| Setting                | Choices                                                 |
| ---------------------- | ------------------------------------------------------- |
| Map style              | Default, Colorful, Natural, Muted, Gray, Toner          |
| Theme mode             | Auto follows Home Assistant; Light and Dark override it |
| Map height             | 240–1,000 pixels; default 400                           |
| Initial forecast layer | Road condition or slipperiness                          |
| Legend expanded        | Off by default                                          |

Under **Road cameras** and **Weather stations**, enable the sources you want to
see. The card discovers them automatically; you do not need to add each camera
or station to the integration first. Both layers are off by default, with
visibility controlled only in the card editor.

Each layer has its own maximum distance from the saved route: **250 metres** by
default, adjustable from 1 to 2,000 metres. This is independent of the forecast
corridor and map zoom. Nearby side roads can fall within that distance too.

Tap a camera for its still image and source status, or a weather station for its
measured air temperature and observation time. Overlapping sources share a
counted marker. Groups containing both cameras and weather stations show both
icons. Tap a group to open a list with separate weather and camera sections,
then choose a source. Camera directions appear below the name where available.
Neither action changes the map's position or zoom. After closing the details,
the choices return for eight seconds; hovering or keeping keyboard focus inside
keeps them open. Nearby sources separate as you zoom in; coincident sources stay
grouped.

Cards share discovery caches. While a layer is shown, weather observations
refresh every ten minutes and the camera catalogue every fifteen minutes.
Only an open camera requests an image, at most once a minute while its page is
visible. Multiple viewers share a short-lived image cache; manually added
cameras reuse their existing HA cache. The source image may remain unchanged
between requests, and its capture time is not supplied.

An unavailable source feed clears its layer and shows a message; other layers
continue independently. A failed still shows **Image unavailable**. Missing
coordinates prevent a source from appearing on the map. Automatically discovered
sources do not create devices, entities or recorder history. Add a source
manually if you also want its entities for dashboards or automations.

In Automatic mode, cards share the route's forecast data without extra polling.
Browsing another hour requests only that hour; cards and actions share its cache.
If the background map cannot load, route geometry remains
usable. If the forecast becomes unavailable, its colored segments are cleared
until recovery. Text sensors remain usable without WebGL 2.

<details>
<summary>YAML configuration and alternative map providers</summary>

The visual editor fills in the route's device ID. Equivalent YAML:

```yaml
type: custom:vegvesen-route-map
device_id: YOUR_ROUTE_DEVICE_ID
map_style: default
theme_mode: auto
height: 400
default_mode: condition
legend_expanded: false
show_cameras: false
camera_distance_m: 250
show_weather: false
weather_distance_m: 250
```

Only `type` and `device_id` are required. Optional `title` sets a card heading.
Use `default_mode: slip` to start with slipperiness. Style and theme values use
the lowercase names shown in the table above.

Advanced users can set `map_style_url` to a public HTTP(S) MapLibre style URL,
subject to that provider's terms and attribution requirements. It overrides the
built-in map style. Its own colors apply; Theme mode still controls the card UI.

</details>

## Updates and removal

Install updates through HACS, then **restart Home Assistant** and refresh the
browser or reopen the companion app. Reloading the integration alone does not
load updated code. A host reboot is unnecessary.

Use numbered stable releases for normal use. HACS's **Redownload** menu lets you
[select a version](https://www.hacs.xyz/docs/use/repositories/dashboard/#downloading-a-specific-version-of-a-repository),
including when switching from `main`. See the
[release notes](https://github.com/RonnyAL/ha-vegvesen/releases) for changes.

Remove individual sources or routes from the integration in **Devices &
services**. To uninstall completely, remove the integration entry, remove its
download in HACS, and restart Home Assistant.

## Troubleshooting and support

| Problem                                  | What to check                                                                                                                        |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Integration missing after installation   | Confirm HACS downloaded it, restart Home Assistant, then search in **Add integration**.                                              |
| Old or missing labels after an update    | Restart Home Assistant and refresh the browser/app. If only the companion app is affected, use its **Reset frontend cache** setting. |
| Map card missing from the card picker    | Configure the integration, then refresh the browser or fully close and reopen the companion app.                                     |
| Station or camera missing from selection | Check **Unknown county → Unknown municipality** for unclassified sources. Cached lists can take up to 15 minutes to reflect changes. |
| Forecast time is in the recent past      | With 0 hours ahead, this is the start of the current hour. It advances after the next successful hourly refresh.                     |
| Unavailable data or rate-limit message   | Check **Settings → System → Logs** and allow another refresh. Server retry delays are respected.                                     |
| Route calculation times out              | Retry or edit the endpoints. The routing request has a 30-second timeout; entered settings are retained.                              |

[Report a problem](https://github.com/RonnyAL/ha-vegvesen/issues) with the Home
Assistant and integration versions, affected feature, and relevant error
messages. Include public source IDs if useful. Remove credentials, private
locations and other personal details from logs and screenshots.

## Privacy

Route calculation sends endpoint coordinates to Statens vegvesen; forecast
requests send the route's bounding rectangle and forecast time. Saved route
settings and geometry are stored in Home Assistant.

Map previews request OpenStreetMap tiles from the Home Assistant server.
Interactive maps request vector tiles and label fonts directly from your
browser. The provider receives the requested map areas and the requesting IP
address; browser requests also include the Home Assistant site's origin as a
referrer. Route names and complete route geometry are not uploaded to the map
provider. Map requests are made on demand and cached.

## Data and licensing

**Data provided by Statens vegvesen / Data levert av Statens vegvesen.**

- **Weather, camera and routing data:** published under NLOD. See the
  [weather](https://dataut.vegvesen.no/nb/dataservice/vaerdata-malinger-api),
  [camera](https://dataut.vegvesen.no/en/dataset/webkamera) and
  [routing](https://dataut.vegvesen.no/nb/dataset/ruteplandata-bil) catalogues.
- **Road-condition forecasts:** provided by the
  [Vegvær map service](https://www.vegvesen.no/fag/teknologi/apne-data/et-utvalg-apne-data/ogc-karttjenester/kartlag/).
  See the [API documentation notes](docs/route-forecasts.md) for source details
  and licensing limitations.
- **Administrative geography:** [© Kartverket](https://www.kartverket.no/),
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), under
  [Kartverket's terms of use](https://www.kartverket.no/api-og-data/vilkar-for-bruk).
- **Background maps:** [© OpenStreetMap contributors](https://www.openstreetmap.org/copyright),
  subject to the [raster](https://operations.osmfoundation.org/policies/tiles/)
  and [vector](https://operations.osmfoundation.org/policies/vector/) tile policies.

Integration code is licensed under [MIT](LICENSE), retaining the license and
attribution of [ludeeus/integration_blueprint](https://github.com/ludeeus/integration_blueprint).
See the [data attribution notice](custom_components/vegvesen/NOTICE.md) and
[frontend licenses](custom_components/vegvesen/frontend/LICENSES.md) for full
credits, including MapLibre, VersaTiles and Home Assistant's map palette.

For contribution guidelines and development documentation, see
[CONTRIBUTING.md](CONTRIBUTING.md).
