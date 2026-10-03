# Statens vegvesen for Home Assistant

Bring road weather readings and road-camera still images from Statens vegvesen into Home Assistant. Choose the stations and cameras you want, anywhere in Norway.

| Source | Entities | Refresh interval |
| --- | --- | --- |
| Weather station | Air temperature and observation time | 10 minutes |
| Road camera | Still image and source availability | 1 minute |

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

Choose **Weather station / Værstasjon** or **Road camera / Veikamera**. An overview shows your current choices and provides actions to:

1. Choose a **county / fylke**.
2. Choose a **municipality / kommune**.
3. Select one or more stations or cameras.
4. Choose **Add / Legg til** to save them.

Each editor returns to the overview with **Done / Ferdig**. Use **Change county / Endre fylke**, **Change municipality / Endre kommune**, or the source selection action to revise your draft before adding it. Changing county clears the municipality and source choices; changing municipality clears the source choices. Keeping the same region preserves them.

Only counties and municipalities with sources of the selected type appear. Source labels show the name, camera direction where available, and source ID. You can select several sources from the current municipality before saving.

New or relocated sources without verified administrative membership appear under **Unknown county / Ukjent fylke → Unknown municipality / Ukjent kommune**. Their measurements and identities are unchanged.

Use **Add weather stations / Legg til værstasjoner** or **Add road cameras / Legg til veikameraer** on the same integration to add more sources. Each selection can be anywhere in Norway; selecting one region does not restrict later selections. The same source cannot be added twice. Existing selections and device/entity identities are retained across updates and restarts.

Discovery lists are reused for up to 15 minutes. The first list after startup or cache expiry needs a complete response from Statens vegvesen; later selections usually open faster. All selected sources are checked again when you choose **Add**. If a request fails or a selected source is missing or already configured, nothing from that batch is added; you can adjust the selection and retry.

## Using the entities

Each source creates a device in **Settings → Devices & services**. Add its entities to a dashboard or use them in automations.

- **Air temperature** uses the source's measurement. Home Assistant displays it in your preferred temperature unit.
- **Observation time** tells you when the weather reading was measured. It can differ from the last refresh time.
- **Road camera** displays the latest retrieved still image. Images can remain unchanged when the source does not publish a new one.
- **Source availability** reports the camera status supplied by Statens vegvesen.

Readings and statuses are exposed as provided by the source. Missing readings are **unknown**. Request failures make the affected entities **unavailable**, and they recover after a successful refresh. A failed camera image does not prevent weather readings or other camera images from updating.

## Updates and removal

Update or redownload the integration in HACS, then restart Home Assistant. This repository currently distributes the default branch; HACS may show a commit identifier instead of the version displayed in the integration details.

To remove one source, remove its station/camera subentry in **Devices & services**. To remove everything, remove the integration entry, remove the download in HACS, and restart Home Assistant.

## Troubleshooting and support

**The integration does not appear:** confirm HACS downloaded it, restart Home Assistant, then search again in **Add integration**.

**Blank fields, old setup text or a `MISSING_VALUE` error after updating:** confirm the integration reports **0.5.0 or newer**, restart HA, then refresh the browser. If the companion app still shows old text, compare with a fresh browser window: restarting HA alone does not clear the app’s cached frontend translations.

**A source is missing:** check the appropriate county/municipality, including **Unknown county → Unknown municipality** for unclassified sources. Newly added sources can take up to 15 minutes to appear in a reused discovery list.

**A reading or image is unavailable:** check **Settings → System → Logs**, then allow another refresh. Source faults and outages can affect individual stations or cameras. Camera metadata publication times do not establish when an image was captured.

[Report a problem](https://github.com/RonnyAL/ha-vegvesen/issues) with your Home Assistant version, integration version, entity type, source ID if you are comfortable sharing it, and relevant error messages. Remove credentials and private details from logs or screenshots.

## Data and licensing

**Data provided by Statens vegvesen / Data levert av Statens vegvesen.** Weather and camera data use [NLOD](https://dataut.vegvesen.no/nb/dataservice/vaerdata-malinger-api); see also the [camera dataset](https://dataut.vegvesen.no/en/dataset/webkamera).

Administrative geography: [© Kartverket](https://www.kartverket.no/), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), under [Kartverket's terms of use](https://www.kartverket.no/api-og-data/vilkar-for-bruk).

The integration uses the [MIT license](LICENSE) and retains the license and attribution of [ludeeus/integration_blueprint](https://github.com/ludeeus/integration_blueprint). The road/weather icon is original artwork, not Statens vegvesen's official logo.

For contributing and development documentation, see [CONTRIBUTING.md](CONTRIBUTING.md).
