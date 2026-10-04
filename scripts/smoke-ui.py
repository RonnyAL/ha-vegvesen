"""Exercise actual HA source-selection UI in a disposable loopback instance."""

import argparse
import json
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import requests
from playwright.sync_api import Page, WebSocket, expect, sync_playwright
from smoke_instance import SmokeInstance, handle_termination

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:18123"
EXPECTED_WEATHER_STATIONS = 2
RESULTS = ROOT / ".tools/smoke-results"


def wait_for_source_picker(page: Page) -> None:
    """Allow one normal Retry after an upstream discovery failure."""
    picker = page.locator("ha-selector-select ha-select")
    retry = page.get_by_role("button", name="Retry", exact=True)
    picker.or_(retry).wait_for(state="visible")
    if retry.is_visible():
        print("Live discovery failed; exercising the native Retry action once")
        retry.click()
    expect(picker).to_be_visible(timeout=45000)


def verify_norwegian_names(options: list[dict]) -> None:
    """Check a real multilingual municipality in the rendered selector options."""
    names = [option["label"] for option in options]
    if "Røros" not in names or "Rosse" in names:
        raise AssertionError("Municipality labels must use Norwegian names")


def verify_sensor_icons(page: Page, route_states: dict) -> None:
    """Check rendered entity icons through HA's ordinary more-info dialog."""
    for suffix, icon in (
        ("road_condition_forecast", "mdi:road-variant"),
        ("slipperiness_forecast", "mdi:car-traction-control"),
        ("forecast_road_segments", "mdi:counter"),
    ):
        entity_id = next(key for key in route_states if key.endswith(suffix))
        page.locator("home-assistant").evaluate(
            "(element, id) => element.dispatchEvent("
            "new CustomEvent('hass-more-info', "
            "{detail: {entityId: id}, bubbles: true, composed: true}))",
            entity_id,
        )
        expect(
            page.locator("ha-more-info-dialog ha-state-icon ha-icon").first
        ).to_have_js_property("icon", icon)
        page.keyboard.press("Escape")
        expect(page.locator("ha-more-info-dialog")).to_be_hidden()
    print("Native route sensor icons rendered from icons.json")


def run_browser(tokens: dict, session: requests.Session) -> None:
    """Create a parent and add a second source through frontend dialogs."""
    tokens.update(
        {
            "hassUrl": BASE,
            "clientId": BASE + "/",
            "expires": time.time() * 1000 + 1800000,
        }
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_default_timeout(45000)

        def trace_websocket(socket: WebSocket) -> None:
            commands = {}

            def sent(payload: str | bytes) -> None:
                message = json.loads(payload)
                if "id" in message:
                    commands[message["id"]] = message.get("type")

            def received(payload: str | bytes) -> None:
                batch = json.loads(payload)
                for message in batch if isinstance(batch, list) else [batch]:
                    if message.get("error"):
                        print(
                            "Frontend websocket error:",
                            commands.get(message.get("id")),
                            message["error"].get("code"),
                        )

            socket.on("framesent", sent)
            socket.on("framereceived", received)

        page.on("websocket", trace_websocket)
        page.on("pageerror", lambda error: print("Frontend error:", error))
        page.on(
            "console",
            lambda message: (
                print(message.text)
                if message.text.startswith("Smoke frontend rejection:")
                else None
            ),
        )
        page.add_init_script("""window.addEventListener('unhandledrejection', event => {
            const reason = event.reason;
            console.warn('Smoke frontend rejection:', JSON.stringify({
                code: reason?.code, message: reason?.message
            }));
        });""")
        page.add_init_script(
            f"localStorage.setItem('hassTokens', {json.dumps(json.dumps(tokens))});"
        )
        try:
            page.goto(BASE + "/config/integrations")
            page.get_by_role("button", name="Add integration", exact=True).wait_for()
            print("Isolated frontend loaded")
            page.get_by_role("button", name="Add integration", exact=True).click()
            page.get_by_role("textbox", name="Search for a brand name").or_(
                page.get_by_placeholder("Search for a brand name")
            ).fill("Statens vegvesen")
            page.get_by_text("Statens vegvesen", exact=True).click()
            weather_started = time.monotonic()
            page.get_by_text("Weather station", exact=True).click()
            picker = page.locator("ha-selector-select")

            def action(label: str) -> None:
                page.get_by_text(label, exact=True).click()

            def select_region(label: str) -> None:
                picker.locator("ha-select").click()
                page.locator("ha-dropdown-item, ha-list-item").get_by_text(
                    label, exact=True
                ).click()
                value = picker.evaluate(
                    "(element, label) => element.selector.select.options.find("
                    "option => option.label === label).value",
                    label,
                )
                expect(picker).to_have_js_property("value", value)

            def select_source(label: str) -> None:
                checkbox = picker.get_by_role("checkbox", name=label, exact=True)
                picker.get_by_text(label, exact=True).click()
                expect(checkbox).to_be_checked()

            def submit(*, final: bool = False) -> None:
                key = "submit" if final else "next"
                label = page.locator("home-assistant").evaluate(
                    "(element, key) => element.hass.localize("
                    "'ui.panel.config.integrations.config_flow.' + key)",
                    key,
                )
                page.get_by_role("button", name=label, exact=True).click()

            def done(label: str = "Done") -> None:
                page.get_by_role("button", name=label, exact=True).click()

            def wait_for_parent_reload() -> None:
                # HA disables its parent chooser while an entry is reloading.
                # Observe the public API before opening the next subentry flow.
                page.locator("home-assistant").evaluate("""async element => {
                    for (let attempt = 0; attempt < 90; attempt++) {
                        const entries = await element.hass.callWS({
                            type: 'config_entries/get', domain: 'vegvesen'
                        });
                        if (entries.length === 1 && entries[0].state === 'loaded')
                            return;
                        await new Promise(resolve => setTimeout(resolve, 500));
                    }
                    throw new Error('Parent reload did not finish');
                }""")

            def choose_region(
                county: str, municipality: str, *, norwegian: bool = False
            ) -> None:
                expect(picker).to_have_js_property(
                    "label", "Fylke" if norwegian else "County"
                )
                select_region(county)
                submit()
                expect(picker).to_have_js_property(
                    "label", "Kommune" if norwegian else "Municipality"
                )
                if county == "Trøndelag":
                    options = picker.evaluate(
                        "element => element.selector.select.options"
                    )
                    verify_norwegian_names(options)
                select_region(municipality)
                submit()

            wait_for_source_picker(page)
            weather_list_seconds = time.monotonic() - weather_started
            choose_region("Trøndelag", "Orkland")
            submit(final=True)
            expect(
                page.get_by_text("Select at least one option.", exact=True)
            ).to_be_visible()
            select_source("Fv 714 Våvatnet (1629006)")
            select_source("Fv 65 Bye (1629004)")
            page.screenshot(path=str(RESULTS / "weather-selection.png"))
            submit(final=True)
            page.get_by_role("button", name="Skip and finish", exact=True).click()
            print("Two weather stations created together through UI")
            page.goto(BASE + "/config/integrations/integration/vegvesen")
            camera_started = time.monotonic()
            page.get_by_role("button", name="Add road cameras", exact=True).click()
            wait_for_source_picker(page)
            camera_list_seconds = time.monotonic() - camera_started
            choose_region("Møre og Romsdal", "Herøy")
            select_source("Rundebrua — Runde (3000047_2)")
            page.screenshot(path=str(RESULTS / "camera-selection.png"))
            submit(final=True)
            page.get_by_role("button", name="Finish", exact=True).click()
            expect(page.get_by_role("button", name="Finish", exact=True)).to_be_hidden()
            print("Camera subentry added through UI")
            wait_for_parent_reload()
            page.get_by_role("button", name="Add route", exact=True).click()
            name_input = page.locator("ha-selector-text input")
            expect(name_input).to_have_count(1)
            name_input.fill("Trondheim-Orkanger")
            page.get_by_role("button", name="Continue", exact=True).click()
            locations = page.locator("ha-selector-location")
            expect(locations).to_have_count(2)
            for location, latitude, longitude in [
                (locations.nth(0), "63.43", "10.395"),
                (locations.nth(1), "63.305", "9.846"),
            ]:
                numbers = location.locator("ha-selector-number")
                expect(numbers.nth(0)).to_have_js_property("label", "Latitude")
                expect(numbers.nth(1)).to_have_js_property("label", "Longitude")
                numbers.nth(0).locator("input").fill(latitude)
                numbers.nth(1).locator("input").fill(longitude)
            page.get_by_role("button", name="Calculate route", exact=True).click()
            expect(page.get_by_text("Change settings", exact=True)).to_be_visible()
            action("Choose route")
            expect(picker).to_have_js_property("label", "Route")
            done()
            expect(page.get_by_text("Save route", exact=True)).to_be_visible()
            page.screenshot(path=str(RESULTS / "route-overview.png"))
            action("Save route")
            page.get_by_role("button", name="Finish", exact=True).click()
            expect(page.get_by_role("button", name="Finish", exact=True)).to_be_hidden()
            print("Saved road route configured through native frontend")
            # Saving a subentry reloads its parent. Opening HA's parent chooser
            # during that reload can leave it showing a disabled entry.
            wait_for_parent_reload()
            warm_started = time.monotonic()
            page.get_by_role("button", name="Add weather stations", exact=True).click()
            parent_choice = page.get_by_role("dialog").get_by_text(
                "Statens vegvesen", exact=True
            )
            county_field = picker.locator("ha-select")
            county_field.or_(parent_choice).wait_for(state="visible")
            if parent_choice.is_visible():
                parent_choice.click()
            expect(county_field).to_be_visible()
            warm_list_seconds = time.monotonic() - warm_started
            page.get_by_role("button", name="Close", exact=True).click()
            expect(county_field).to_have_count(0)
            # Use HA's normal language event and freshly loaded translation resources.
            page.locator("home-assistant").evaluate("""element =>
                element.dispatchEvent(new CustomEvent('hass-language-select', {
                    detail: 'nb', bubbles: true, composed: true
                }))""")
            page.wait_for_function(
                "document.querySelector('home-assistant').hass.language === 'nb'"
            )
            page.reload()
            for family, county_label, municipality_label, source_label, field_label in [
                (
                    "weather_station",
                    "Trøndelag",
                    "Orkland",
                    "Fv 714 Våvatnet (1629006)",
                    "Værstasjoner",
                ),
                (
                    "camera",
                    "Møre og Romsdal",
                    "Herøy",
                    "Rundebrua — Runde (3000047_2)",
                    "Veikameraer",
                ),
            ]:
                add_label = (
                    "Legg til værstasjoner"
                    if family == "weather_station"
                    else "Legg til veikameraer"
                )
                page.get_by_role("button", name=add_label, exact=True).click()
                county_field = picker.locator("ha-select")
                county_field.or_(parent_choice).wait_for(state="visible")
                if parent_choice.is_visible():
                    parent_choice.click()
                choose_region(county_label, municipality_label, norwegian=True)
                expect(picker).to_have_js_property("label", field_label)
                select_source(source_label)
                expect(page.get_by_text("MISSING_VALUE", exact=False)).to_have_count(0)
                expect(page.get_by_role("link", name="© Kartverket")).to_have_count(0)
                expect(page.get_by_text("Valgt:", exact=False)).to_have_count(0)
                page.screenshot(path=str(RESULTS / f"{family}-bokmal.png"))
                close_label = page.locator("home-assistant").evaluate(
                    "element => element.hass.localize('ui.common.close')"
                )
                page.get_by_role("button", name=close_label, exact=True).click()
                expect(county_field).to_have_count(0)
            print("English and Norwegian checkbox forms and source labels verified")
            page.get_by_role("button", name="Legg til rute", exact=True).click()
            expect(page.locator("ha-selector-text input")).to_have_value("")
            endpoints = page.locator("ha-selector-select")
            expect(endpoints).to_have_count(2)

            def choose_endpoint(index: int, label: str) -> None:
                field = endpoints.nth(index).locator("ha-select")
                field.click()
                endpoints.nth(index).locator(
                    "ha-dropdown-item, ha-list-item"
                ).get_by_text(label, exact=True).click()
                value = endpoints.nth(index).evaluate(
                    "(element, label) => element.selector.select.options.find("
                    "option => option.label === label).value",
                    label,
                )
                expect(endpoints.nth(index)).to_have_js_property("value", value)

            expect(endpoints.nth(0)).to_have_js_property("label", "Start")
            expect(endpoints.nth(1)).to_have_js_property("label", "Mål")
            choose_endpoint(0, "Trondheim (zone.trondheim)")
            choose_endpoint(1, "Orkanger (zone.orkanger)")
            expect(page.locator("ha-selector-location")).to_have_count(0)
            page.screenshot(path=str(RESULTS / "route-zones-bokmal.png"))
            page.get_by_role("button", name="Fortsett", exact=True).click()
            expect(page.get_by_text("Trondheim → Orkanger", exact=True)).to_be_visible()
            for label in (
                "Endre innstillinger",
                "Velg ruteforslag",
                "Beregn ruten på nytt",
                "Lagre rute",
            ):
                expect(page.get_by_text(label, exact=True)).to_be_visible()
            page.screenshot(path=str(RESULTS / "route-overview-bokmal.png"))
            action("Velg ruteforslag")
            expect(picker).to_have_js_property("label", "Rute")
            done("Ferdig")
            action("Endre innstillinger")
            expect(endpoints.nth(0)).to_have_js_property("value", "zone.trondheim")
            choose_endpoint(1, "Velg på kart")
            page.get_by_role("button", name="Fortsett", exact=True).click()
            expect(page.locator("ha-selector-location")).to_have_count(1)
            expect(page.locator("ha-selector-location")).to_have_js_property(
                "label", "Mål"
            )
            page.get_by_role("button", name="Beregn rute", exact=True).click()
            expect(page.get_by_text("Lagre rute", exact=True)).to_be_visible()
            expect(page.get_by_text("MISSING_VALUE", exact=False)).to_have_count(0)
            close_label = page.locator("home-assistant").evaluate(
                "element => element.hass.localize('ui.common.close')"
            )
            page.get_by_role("button", name=close_label, exact=True).click()
            page.get_by_role("button", name="Endre rute", exact=True).click()
            expect(page.get_by_text("Lagre rute", exact=True)).to_be_visible()
            action("Endre innstillinger")
            expect(endpoints.nth(0)).to_have_js_property("value", "map")
            page.get_by_role("button", name=close_label, exact=True).click()
            expect(page.locator("dialog-data-entry-flow")).to_be_hidden()
            print("Bokmål route labels, zones and reconfiguration verified")
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                response = session.get(BASE + "/api/states", timeout=10)
                response.raise_for_status()
                states = response.json()
                cameras = [
                    state
                    for state in states
                    if state["entity_id"].startswith("camera.")
                ]
                temperatures = [
                    state
                    for state in states
                    if state["attributes"].get("device_class") == "temperature"
                    and not state["entity_id"].startswith("sensor.trondheim_orkanger_")
                ]
                observations = [
                    state
                    for state in states
                    if state["attributes"].get("device_class") == "timestamp"
                    and state["entity_id"] == "sensor.fv_714_vavatnet_observation_time"
                ]
                route_states = {
                    state["entity_id"]: state
                    for state in states
                    if state["entity_id"].startswith("sensor.trondheim_orkanger_")
                }
                if (
                    cameras
                    and len(temperatures) == EXPECTED_WEATHER_STATIONS
                    and observations
                    and cameras[0]["state"] != "unavailable"
                    and temperatures[0]["state"] != "unavailable"
                    and observations[0]["state"] != "unavailable"
                    and len(route_states) == 6  # noqa: PLR2004
                    and all(
                        state["state"] not in {"unknown", "unavailable"}
                        for state in route_states.values()
                    )
                ):
                    break
                time.sleep(1)
            else:
                raise RuntimeError(
                    "Weather/camera/route entities did not become available"
                )
            camera = cameras[0]
            image = session.get(
                BASE + camera["attributes"]["entity_picture"], timeout=10
            )
            image.raise_for_status()
            if not image.content.startswith(b"\xff\xd8"):
                raise RuntimeError("Camera proxy did not return a JPEG")
            page.get_by_text("3 enheter", exact=False).first.wait_for(state="visible")
            page.get_by_text("1 tjeneste", exact=False).first.wait_for(state="visible")
            page.screenshot(path=str(RESULTS / "integration.png"))
            verify_sensor_icons(page, route_states)
            page.locator("home-assistant").evaluate(
                "(element, id) => element.dispatchEvent("
                "new CustomEvent('hass-more-info', "
                "{detail: {entityId: id}, bubbles: true, composed: true}))",
                camera["entity_id"],
            )
            picture = page.locator("more-info-camera img").first
            expect(picture).to_be_visible()
            expect(picture).not_to_have_js_property("naturalWidth", 0)
            page.screenshot(path=str(RESULTS / "camera.png"), animations="disabled")
            summary = {
                "ha": session.get(BASE + "/api/config", timeout=10).json()["version"],
                "weather": temperatures[0]["entity_id"],
                "observation": observations[0]["entity_id"],
                "camera": camera["entity_id"],
                "jpeg_bytes": len(image.content),
                "weather_list_seconds": round(weather_list_seconds, 2),
                "camera_list_seconds": round(camera_list_seconds, 2),
                "cached_weather_list_seconds": round(warm_list_seconds, 2),
            }
            (RESULTS / "result.json").write_text(json.dumps(summary, indent=2) + "\n")
            print("UI smoke test passed:", summary)
        except BaseException:
            print("UI URL at failure:", page.url)
            print("Accessible UI:", page.locator("body").aria_snapshot())
            print(
                "Module diagnostics:",
                page.evaluate("""() => ({
                nativeSelects: document.querySelector("home-assistant") !== null,
                modules: performance.getEntriesByType('resource')
                    .filter(entry => entry.name.includes('/vegvesen/frontend/'))
                    .map(entry => entry.name)
            })"""),
            )
            page.screenshot(path=str(RESULTS / "failure.png"))
            raise
        finally:
            browser.close()


def main() -> None:
    """Run the packaged UI against either locked HA target."""
    global BASE, RESULTS  # noqa: PLW0603
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minimum", action="store_true")
    args = parser.parse_args()
    port = 18124 if args.minimum else 18123
    python = (
        ROOT / "environments/minimum/.venv/bin/python"
        if args.minimum
        else Path(sys.executable)
    )
    if args.minimum:
        RESULTS = ROOT / ".tools/smoke-results-minimum"
    with TemporaryDirectory(prefix="vegvesen-smoke-", dir=ROOT / ".tools") as temporary:
        config = Path(temporary)
        version = json.loads(
            (ROOT / "custom_components/vegvesen/manifest.json").read_text()
        )["version"]
        with ZipFile(ROOT / ".tools/packages" / f"vegvesen-{version}.zip") as archive:
            archive.extractall(config)
        print("Testing an extracted runtime package, without a source-tree link")
        instance = SmokeInstance(config, RESULTS, python, port)
        BASE = instance.base
        try:
            instance.start()
            instance.onboard()
            run_browser(instance.tokens, instance.session)
        finally:
            instance.stop()
    print("Disposable configuration and authentication storage removed")


if __name__ == "__main__":
    handle_termination()
    main()
