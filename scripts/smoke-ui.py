"""Exercise actual HA source-selection UI in a disposable loopback instance."""

import json
import secrets
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import requests
from playwright.sync_api import WebSocket, expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:18123"
EXPECTED_WEATHER_STATIONS = 2
RESULTS = ROOT / ".tools/smoke-results"


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
            # HA asks to confirm the isolated HTTP binding on first startup.
            page.get_by_role("button", name="Confirm", exact=True).click()
            print("Isolated frontend loaded; HTTP binding confirmed")
            page.get_by_role("button", name="Add integration", exact=True).click()
            page.get_by_placeholder("Search for a brand name").fill("Statens vegvesen")
            page.get_by_text("Statens vegvesen", exact=True).click()
            weather_started = time.monotonic()
            page.get_by_text("Weather station", exact=True).click()
            picker = page.locator("ha-selector-select")

            def action(label: str) -> None:
                page.get_by_text(label, exact=True).click()

            def select_region(label: str) -> None:
                picker.locator("ha-picker-field").click()
                page.locator("ha-dropdown-item").get_by_text(label, exact=True).click()
                expect(picker.locator("ha-picker-field")).to_have_js_property(
                    "value", label
                )

            def select_source(label: str) -> None:
                picker.locator("ha-generic-picker ha-button").click()
                page.locator("ha-picker-combo-box").get_by_text(
                    label, exact=True
                ).click()
                expect(
                    picker.locator("ha-input-chip").filter(has_text=label)
                ).to_be_visible()

            def done(label: str = "Done") -> None:
                page.get_by_role("button", name=label, exact=True).click()

            def choose_region(
                county: str, municipality: str, *, norwegian: bool = False
            ) -> None:
                action("Velg fylke" if norwegian else "Choose county")
                expect(picker.locator("ha-picker-field")).to_have_js_property(
                    "label", "Fylke" if norwegian else "County"
                )
                select_region(county)
                done("Ferdig" if norwegian else "Done")
                action("Velg kommune" if norwegian else "Choose municipality")
                expect(picker.locator("ha-picker-field")).to_have_js_property(
                    "label", "Kommune" if norwegian else "Municipality"
                )
                select_region(municipality)
                done("Ferdig" if norwegian else "Done")

            expect(page.get_by_text("Choose county", exact=True)).to_be_visible()
            weather_list_seconds = time.monotonic() - weather_started
            expect(page.get_by_text("Choose municipality", exact=True)).to_have_count(0)
            choose_region("Trøndelag", "Orkland")
            action("Select weather stations")
            done()
            expect(page.get_by_text("Add", exact=True)).to_have_count(0)
            action("Select weather stations")
            select_source("Fv 714 Våvatnet (1629006)")
            select_source("Fv 65 Bye (1629004)")
            page.screenshot(path=str(RESULTS / "weather-selection.png"))
            done()
            expect(page.get_by_text("Change county", exact=True)).to_be_visible()
            action("Change municipality")
            expect(picker.locator("ha-picker-field")).to_have_js_property(
                "value", "Orkland"
            )
            done()
            action("Change county")
            expect(picker.locator("ha-picker-field")).to_have_js_property(
                "value", "Trøndelag"
            )
            done()
            expect(page.get_by_text("Add", exact=True)).to_be_visible()
            page.screenshot(path=str(RESULTS / "weather-overview.png"))
            action("Add")
            page.get_by_role("button", name="Skip and finish", exact=True).click()
            print("Two weather stations created together through UI")
            page.goto(BASE + "/config/integrations/integration/vegvesen")
            camera_started = time.monotonic()
            page.get_by_role("button", name="Add road cameras", exact=True).click()
            expect(page.get_by_text("Choose county", exact=True)).to_be_visible()
            camera_list_seconds = time.monotonic() - camera_started
            choose_region("Møre og Romsdal", "Herøy")
            action("Select road cameras")
            select_source("Rundebrua — Runde (3000047_2)")
            page.screenshot(path=str(RESULTS / "camera-selection.png"))
            done()
            action("Add")
            page.get_by_role("button", name="Finish", exact=True).click()
            expect(page.get_by_role("button", name="Finish", exact=True)).to_be_hidden()
            print("Camera subentry added through UI")
            page.get_by_role("button", name="Add route", exact=True).click()
            name_input = page.locator("ha-selector-text input")
            expect(name_input).to_have_count(1)
            name_input.fill("Trondheim-Orkanger")
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
            expect(picker.locator("ha-picker-field")).to_have_js_property(
                "label", "Route"
            )
            done()
            expect(page.get_by_text("Save route", exact=True)).to_be_visible()
            page.screenshot(path=str(RESULTS / "route-overview.png"))
            action("Save route")
            page.get_by_role("button", name="Finish", exact=True).click()
            expect(page.get_by_role("button", name="Finish", exact=True)).to_be_hidden()
            print("Saved road route configured through native frontend")
            # Saving a subentry reloads its parent. Opening HA's parent chooser
            # during that reload can leave it showing a disabled entry.
            page.locator("ha-config-integration-page").evaluate("""async element => {
                for (let attempt = 0; attempt < 90; attempt++) {
                    const entries = (
                        element._extraConfigEntries || element.configEntries)
                        ?.filter(entry => entry.domain === 'vegvesen');
                    const routes = Object.keys(element.hass.states).filter(
                        id => id.startsWith('sensor.trondheim_orkanger_'));
                    if (entries?.length === 1 && entries[0].state === 'loaded'
                        && routes.length === 6) return;
                    await new Promise(resolve => setTimeout(resolve, 500));
                }
                throw new Error('Frontend did not finish the parent reload');
            }""")
            warm_started = time.monotonic()
            page.get_by_role("button", name="Add weather stations", exact=True).click()
            parent_choice = page.get_by_role("dialog").get_by_text(
                "Statens vegvesen", exact=True
            )
            overview = page.get_by_text("Choose county", exact=True)
            overview.or_(parent_choice).wait_for(state="visible")
            if parent_choice.is_visible():
                parent_choice.click()
            expect(overview).to_be_visible()
            warm_list_seconds = time.monotonic() - warm_started
            page.keyboard.press("Escape")
            expect(overview).to_have_count(0)
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
                overview = page.get_by_text("Velg fylke", exact=True)
                overview.or_(parent_choice).wait_for(state="visible")
                if parent_choice.is_visible():
                    parent_choice.click()
                choose_region(county_label, municipality_label, norwegian=True)
                action(
                    "Velg værstasjoner"
                    if family == "weather_station"
                    else "Velg veikameraer"
                )
                expect(picker).to_have_js_property("label", field_label)
                select_source(source_label)
                done("Ferdig")
                expect(page.get_by_text("MISSING_VALUE", exact=False)).to_have_count(0)
                expect(page.get_by_role("link", name="© Kartverket")).to_have_count(0)
                action("Endre kommune")
                expect(picker.locator("ha-picker-field")).to_have_js_property(
                    "value", municipality_label
                )
                done("Ferdig")
                action("Endre fylke")
                expect(picker.locator("ha-picker-field")).to_have_js_property(
                    "value", county_label
                )
                done("Ferdig")
                expect(page.get_by_text("Legg til", exact=True)).to_be_visible()
                page.screenshot(path=str(RESULTS / f"{family}-bokmal.png"))
                close_label = page.locator("home-assistant").evaluate(
                    "element => element.hass.localize('ui.common.close')"
                )
                page.get_by_role("button", name=close_label, exact=True).click()
                expect(overview).to_have_count(0)
            print(
                "English and Norwegian visible edit actions and source labels verified"
            )
            page.get_by_role("button", name="Legg til rute", exact=True).click()
            expect(page.locator("ha-selector-location")).to_have_count(2)
            expect(
                page.get_by_role("button", name="Beregn rute", exact=True)
            ).to_be_visible()
            expect(page.get_by_text("MISSING_VALUE", exact=False)).to_have_count(0)
            page.screenshot(path=str(RESULTS / "route-bokmal.png"))
            close_label = page.locator("home-assistant").evaluate(
                "element => element.hass.localize('ui.common.close')"
            )
            page.get_by_role("button", name=close_label, exact=True).click()
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
                "ha": "2026.9.4",
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
    """Create temporary config, onboard a test owner and guarantee shutdown."""
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", 18123))
    RESULTS.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="vegvesen-smoke-", dir=ROOT / ".tools") as temporary:
        config = Path(temporary)
        version = json.loads(
            (ROOT / "custom_components/vegvesen/manifest.json").read_text()
        )["version"]
        with ZipFile(ROOT / ".tools/packages" / f"vegvesen-{version}.zip") as archive:
            archive.extractall(config)
        print("Testing an extracted runtime package, without a source-tree link")
        (config / ".storage").mkdir()
        # Skip optional onboarding integrations and analytics, leaving owner creation.
        (config / ".storage/onboarding").write_text(
            json.dumps(
                {
                    "version": 4,
                    "minor_version": 1,
                    "key": "onboarding",
                    "data": {"done": ["core_config", "analytics", "integration"]},
                }
            )
        )
        (config / "configuration.yaml").write_text(
            "homeassistant:\n  name: Vegvesen isolated smoke test\n"
            "  latitude: 0\n  longitude: 0\n  elevation: 0\n"
            "  time_zone: Europe/Oslo\n  unit_system: metric\n"
            "frontend:\nhttp:\n  server_host: 127.0.0.1\n  server_port: 18123\n"
            "logger:\n  default: warning\n"
            f"ffmpeg:\n  ffmpeg_bin: {ROOT}/.tools/browsers/ffmpeg-1011/ffmpeg-linux\n"
        )
        with (RESULTS / "home-assistant.log").open("w") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-E",  # Ignore an inherited development PYTHONPATH.
                    "-m",
                    "homeassistant",
                    "--config",
                    str(config),
                    "--skip-pip",
                ],
                # The repository's namespace package can otherwise shadow the
                # extracted custom_components package, even with --config set.
                cwd=config,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                session = requests.Session()
                session.trust_env = False
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError(
                            "Temporary HA exited; inspect smoke-results log"
                        )
                    try:
                        if session.get(BASE + "/api/onboarding", timeout=1).ok:
                            break
                    except requests.RequestException:
                        pass
                    time.sleep(0.5)
                else:
                    raise RuntimeError("Temporary HA startup timed out")
                owner = session.post(
                    BASE + "/api/onboarding/users",
                    json={
                        "name": "Smoke test",
                        "username": "smoke",
                        "password": secrets.token_urlsafe(32),
                        "client_id": BASE + "/",
                        "language": "en",
                    },
                    timeout=30,
                )
                owner.raise_for_status()
                response = session.post(
                    BASE + "/auth/token",
                    data={
                        "grant_type": "authorization_code",
                        "code": owner.json()["auth_code"],
                        "client_id": BASE + "/",
                    },
                    timeout=10,
                )
                response.raise_for_status()
                tokens = response.json()
                session.headers["Authorization"] = "Bearer " + tokens["access_token"]
                run_browser(tokens, session)
            finally:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                print("Temporary HA stopped; disposable configuration removed on exit")


if __name__ == "__main__":

    def stop_requested(signum: int, _frame: object) -> None:
        """Let finally clean up the child when the runner receives SIGTERM."""
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, stop_requested)
    main()
