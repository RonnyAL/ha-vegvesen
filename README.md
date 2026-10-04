# Statens vegvesen for Home Assistant

Bring road weather readings, road-camera still images and route forecasts from Statens vegvesen into Home Assistant. Choose your sources and save routes anywhere in Norway.

| Source | Entities | Refresh interval |
| --- | --- | --- |
| Weather station | Air temperature and observation time | 10 minutes |
| Road camera | Still image and source availability | 1 minute |
| Saved route | Forecast road condition, slipperiness, minimum/maximum road temperature, forecast time and segment count | Just after each hour and half-hour |

Setup is available in English and Norwegian Bokmål. No API key or Statens vegvesen account is required.

## Requirements

- Home Assistant **2025.12.0 or newer**.
- [HACS](https://www.hacs.xyz/docs/use/) **2.0.5 or newer** for HACS installation.
- Internet access to Statens vegvesen's public services.

## Install with HACS

This integration is available through a HACS custom repository.

1. Open HACS, then its menu → **Custom repositories**.
2. Add `https://github.com/RonnyAL/ha-vegvesen` with type **Integration**.
3. Find **Statens vegvesen** and download it.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration** and search for **Statens vegvesen**.

See HACS's [custom repository instructions](https://www.hacs.xyz/docs/faq/custom_repositories/) if you cannot find the menu.

For manual installation, copy the repository's `custom_components/vegvesen` folder into your Home Assistant configuration's `custom_components` folder, then restart Home Assistant and add the integration as above.

## Choose stations and cameras

Choose **Weather station / Værstasjon** or **Road camera / Veikamera**.

1. Choose a **county / fylke** and continue.
2. Choose a **municipality / kommune** and continue.
3. Tick one or more stations or cameras, then submit to save them together.

Only counties and municipalities with sources of the selected type appear.
Municipality names use Kartverket's Norwegian names, such as **Kåfjord** and
**Karasjok**. Each checkbox shows the source name, camera direction where
available, and source ID. One batch covers one municipality; start another flow
for sources elsewhere. HA's native forms have no Back button: to change an
earlier region, close and reopen the wizard. The discovery cache is reused.

New or relocated sources without verified administrative membership appear under **Unknown county / Ukjent fylke → Unknown municipality / Ukjent kommune**. Their measurements and identities are unchanged.

Use **Add weather stations / Legg til værstasjoner** or **Add road cameras / Legg til veikameraer** on the same integration to add more sources. Each selection can be anywhere in Norway; selecting one region does not restrict later selections. The same source cannot be added twice. Existing selections and device/entity identities are retained across updates and restarts.

Discovery lists are reused for up to 15 minutes. The first list after startup or cache expiry needs a complete response from Statens vegvesen; later selections usually open faster. Loading and checking sources use HA’s progress screen; cancelling while a request is pending stops that flow without saving its selections. All selected sources are checked again when you submit the final selection. If a request fails or a selected source is missing or already configured, nothing from that batch is added; you can adjust the selection and retry.

## Using the entities

Each source creates a device in **Settings → Devices & services**. Add its entities to a dashboard or use them in automations.

- **Air temperature** uses the source's measurement. Home Assistant displays it in your preferred temperature unit.
- **Observation time** tells you when the weather reading was measured. It can differ from the last refresh time.
- **Road camera** displays the latest retrieved still image. Images can remain unchanged when the source does not publish a new one.
- **Source availability** reports the camera status supplied by Statens vegvesen.

Readings and statuses are exposed as provided by the source. Missing readings are **unknown**. Request failures make the affected entities **unavailable**, and they recover after a successful refresh. A failed camera image does not prevent weather readings or other camera images from updating.

## Route forecasts (føreforhold)

Choose **Add route / Legg til rute** on the integration, or **Route forecast / Ruteprognose** during first setup.

1. Name the route and choose a **start** and **destination** from your existing Home Assistant zones. Each dropdown also offers **Choose on map / Velg på kart**; you can mix zones and map points.
2. Set the **corridor** (distance on either side of the route, initially 100 metres) and **forecast hours ahead** (initially 1).
3. Choose **Continue / Fortsett**. If you selected map points, set those points on the next screen and choose **Calculate route / Beregn rute**. Maps initially centre on your Home Assistant location. Review the proposed road names and distance. **Choose route / Velg ruteforslag** lets you select another proposal if the service offers one.
4. Choose **Save route / Lagre rute**. You can edit the settings from the overview before saving, or use the route's reconfigure action later.

Each saved route creates one device with six sensors. **Road condition** and **Slipperiness** summarize the source categories on matching road segments. A single category is shown when all matched segments agree; differing categories show **Mixed**. If some matched segments lack a category, the summary shows **Incomplete data**; if all lack it, it is **unknown**. Attributes list the original category codes and their counts. Slipperiness comes from the source, without an integration-generated risk score. **No new precipitation** does not mean dry road or safe driving conditions.

The temperature sensors show the lowest and highest available **forecast road-surface temperatures**, preserving unusual source values. These are forecasts, distinct from measured station temperatures. Missing temperatures are omitted from the minimum/maximum and counted in attributes; no available values means **unknown**.

**Forecast valid time / Prognosen gjelder for** is the hour the forecast applies to, not when it was published or fetched. HA may display it as a time in the future; that is expected. With 1 hour ahead selected, a refresh at 14:35 selects the forecast for 15:00. The selected hour advances at the next hourly refresh.

Forecasts are fetched immediately when the route loads, then just after `:00` and `:30`. For example, with 1 hour ahead selected, the refresh just after 15:00 selects 16:00. Statens vegvesen does not advertise a push feed for these road forecasts, so the integration polls. Unchanged source values stay unchanged after a successful refresh. These refresh times do not guarantee that the source has published new data; request failures and server retry delays can postpone updates.

**Forecast segments** counts the matching segments, including ones with missing values. Zero matching segments gives a count of 0 and unknown condition/temperature/time sensors. A failed or incomplete API request makes that route unavailable until a complete refresh succeeds.

The selectable 1–24-hour range does not guarantee that all those forecasts have
been published. Available hours vary with the source forecast; try a nearer hour
if a distant forecast is unknown. The corridor range of 10–2,000 metres controls
which nearby roads are included; it is an integration setting, not an API radius
limit. If the routing service cannot match an endpoint to its road network, the
relevant map or zone field asks you to choose a point closer to a supported road.

Routes have their own geography, independently of selected counties, stations, cameras or other routes. Overlapping routes do not add duplicate stations or cameras. Saved road geometry is reused during polling; **Recalculate route / Beregn ruten på nytt** explicitly requests a fresh road proposal. Zone centres are copied when calculating a route. If you move a zone, recalculate to use its new position. Deleting a zone does not alter an already saved route; select another endpoint before recalculating. Forecasts for one route can fail without stopping the others.

This first version supports two endpoints, without intermediate stops, imported tracks or a route-line map preview. Matching is geographic: nearby side roads, crossing roads and opposite carriageways may be included in the corridor. Forecast coverage is not guaranteed along the entire route. Large routes can exceed the request deadline and become unavailable; partial results are never presented as complete. This version does not include traffic incidents or closures.

For individual segment forecasts, use **Statens vegvesen: Get route forecasts** in **Developer tools → Actions**, selecting the route device. The response contains geometry and unchanged source properties from the latest successful refresh. It makes no extra network request; it fails while the route is unavailable. Full segment geometry is kept out of entity attributes and recorder history.

## Updates and removal

Choose a numbered release in HACS, then restart **Home Assistant** to load the updated integration. A host reboot is unnecessary. Reloading the integration alone does not load upgraded Python code.

If you previously installed `main`, the first transition may show a commit identifier → version number. If needed, open the repository menu in HACS, choose **Update information**, then **Redownload** and select the numbered release. Subsequent release updates show version numbers. Selecting `main` continues to use development commits. See the [release notes](https://github.com/RonnyAL/ha-vegvesen/releases).

To remove one source or route, remove its subentry in **Devices & services**. To remove everything, remove the integration entry, remove the download in HACS, and restart Home Assistant.

## Troubleshooting and support

**The integration does not appear:** confirm HACS downloaded it, restart Home Assistant, then search again in **Add integration**.

**Blank fields, old setup text or a `MISSING_VALUE` error after updating:** confirm HACS has downloaded the latest revision, restart HA, then refresh the browser. If the companion app shows a lone **+**, blank menu buttons, raw field names or old text while a fresh browser works, use **Reset frontend cache** in the app’s settings. Restarting HA alone does not clear the app’s cached frontend translations. See [HA’s cache troubleshooting](https://www.home-assistant.io/faq/).

**A forecast time has passed:** with the default 1-hour offset, it normally advances just after the hour, once the request completes. Longer forecast offsets look further ahead. If the route becomes unavailable, check the logs and allow recovery. A successful refresh can leave condition and temperature values unchanged.

**A source is missing:** check the appropriate county/municipality, including **Unknown county → Unknown municipality** for unclassified sources. Newly added sources can take up to 15 minutes to appear in a reused discovery list.

**A reading or image is unavailable:** check **Settings → System → Logs**, then allow another refresh. Source faults and outages can affect individual stations or cameras. Camera metadata publication times do not establish when an image was captured.

[Report a problem](https://github.com/RonnyAL/ha-vegvesen/issues) with your Home Assistant version, integration version, entity type, source ID if you are comfortable sharing it, and relevant error messages. Remove credentials and private details from logs or screenshots.

## Data and licensing

**Data provided by Statens vegvesen / Data levert av Statens vegvesen.** Weather and camera data use [NLOD](https://dataut.vegvesen.no/nb/dataservice/vaerdata-malinger-api); see also the [camera dataset](https://dataut.vegvesen.no/en/dataset/webkamera).

The [road-routing dataset](https://dataut.vegvesen.no/nb/dataset/ruteplandata-bil) lists NLOD. Road-condition forecasts come from Statens vegvesen's public [Vegvær map service](https://www.vegvesen.no/fag/teknologi/apne-data/et-utvalg-apne-data/ogc-karttjenester/kartlag/). See the [API notes](docs/route-forecasts.md) for verified endpoints and remaining documentation gaps.

Administrative geography: [© Kartverket](https://www.kartverket.no/), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), under [Kartverket's terms of use](https://www.kartverket.no/api-og-data/vilkar-for-bruk).

The integration uses the [MIT license](LICENSE) and retains the license and attribution of [ludeeus/integration_blueprint](https://github.com/ludeeus/integration_blueprint). The road/weather icon is original artwork, not Statens vegvesen's official logo.

For contributing and development documentation, see [CONTRIBUTING.md](CONTRIBUTING.md).
