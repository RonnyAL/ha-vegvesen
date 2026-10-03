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
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:18123"
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
            page.get_by_text("Weather station", exact=True).click()
            print("Weather configuration dialog opened")
            expect(page.get_by_role("link", name="© Kartverket")).to_be_visible()
            page.locator("ha-selector-select ha-picker-field").click()
            page.locator("ha-dropdown-item").filter(has_text="Trøndelag").click()
            page.get_by_role("button", name="Submit", exact=True).click()
            page.locator("ha-selector-select ha-picker-field").nth(1).click()
            page.locator("ha-dropdown-item").filter(has_text="Orkland").click()
            page.get_by_role("button", name="Submit", exact=True).click()
            page.locator("ha-selector-select ha-picker-field").nth(2).click()
            page.locator("ha-dropdown-item").filter(
                has_text="Fv 714 Våvatnet (1629006)"
            ).click()
            page.screenshot(path=str(RESULTS / "weather-selection.png"))
            page.get_by_role("button", name="Submit", exact=True).click()
            page.get_by_role("button", name="Skip and finish", exact=True).click()
            print("Weather parent created through UI")
            page.get_by_text("Statens vegvesen", exact=True).click()
            page.get_by_role("button", name="Add road camera", exact=True).click()
            expect(page.get_by_role("link", name="© Kartverket")).to_be_visible()
            page.locator("ha-selector-select ha-picker-field").click()
            page.locator("ha-dropdown-item").filter(has_text="Møre og Romsdal").click()
            page.get_by_role("button", name="Submit", exact=True).click()
            page.locator("ha-selector-select ha-picker-field").nth(1).click()
            page.locator("ha-dropdown-item").filter(has_text="Herøy").click()
            page.get_by_role("button", name="Submit", exact=True).click()
            page.locator("ha-selector-select ha-picker-field").nth(2).click()
            page.locator("ha-dropdown-item").filter(
                has_text="Rundebrua — Runde (3000047_2)"
            ).click()
            page.screenshot(path=str(RESULTS / "camera-selection.png"))
            page.get_by_role("button", name="Submit", exact=True).click()
            page.get_by_role("button", name="Finish", exact=True).click()
            expect(page.get_by_role("button", name="Finish", exact=True)).to_be_hidden()
            print("Camera subentry added through UI")
            expect(
                page.get_by_text("Fv 714 Våvatnet (1629006)", exact=True)
            ).to_be_visible()
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
                ]
                observations = [
                    state
                    for state in states
                    if state["attributes"].get("device_class") == "timestamp"
                    and state["entity_id"] == "sensor.fv_714_vavatnet_observation_time"
                ]
                if (
                    cameras
                    and temperatures
                    and observations
                    and cameras[0]["state"] != "unavailable"
                    and temperatures[0]["state"] != "unavailable"
                    and observations[0]["state"] != "unavailable"
                ):
                    break
                time.sleep(1)
            else:
                raise RuntimeError("Weather/camera entities did not become available")
            camera = cameras[0]
            image = session.get(
                BASE + camera["attributes"]["entity_picture"], timeout=10
            )
            image.raise_for_status()
            if not image.content.startswith(b"\xff\xd8"):
                raise RuntimeError("Camera proxy did not return a JPEG")
            page.get_by_text("2 devices", exact=False).first.wait_for(state="visible")
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
            }
            (RESULTS / "result.json").write_text(json.dumps(summary, indent=2) + "\n")
            print("UI smoke test passed:", summary)
        except BaseException:
            print("UI URL at failure:", page.url)
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
                    "-m",
                    "homeassistant",
                    "--config",
                    str(config),
                    "--skip-pip",
                ],
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
