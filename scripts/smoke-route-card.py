"""Test the packaged card in a disposable HA and Chromium with public locations."""

import argparse
import json
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from playwright.sync_api import Locator, expect, sync_playwright
from smoke_instance import ROOT, SmokeInstance, handle_termination


def choose_route(selector: Locator) -> None:
    """Use the native picker on both supported frontend generations."""
    selector.get_by_role("button").click()
    if selector.locator("ha-picker-field").count():
        selector.locator("ha-picker-field").click()
        selector.get_by_role("textbox").fill("Trondheim")
    else:
        selector.get_by_role("combobox").fill("Trondheim")
    selector.get_by_text("Trondheim - Orkanger", exact=True).click()


def run(instance: SmokeInstance) -> None:
    """Use supported config/resource APIs, then exercise the real frontend card."""
    base, session = instance.base, instance.session

    def post(path: str, data: dict) -> dict:
        response = session.post(base + path, json=data, timeout=60)
        response.raise_for_status()
        return response.json()

    path = "/api/config/config_entries/flow"
    flow = post(path, {"handler": "vegvesen"})
    path += "/" + flow["flow_id"]
    post(path, {"next_step_id": "route"})
    flow = post(
        path,
        {
            "name": "Trondheim - Orkanger",
            "start_source": "zone.trondheim",
            "end_source": "zone.orkanger",
            "corridor_m": 100,
            "forecast_hours": 0,
        },
    )
    for _ in range(60):
        if flow["type"] not in {"progress", "progress_done"}:
            break
        time.sleep(0.5)
        flow = session.get(base + path, timeout=60).json()
    assert flow["step_id"] == "route_overview", flow
    assert post(path, {"next_step_id": "route_save"})["type"] == "create_entry"
    for _ in range(60):
        states = session.get(base + "/api/states", timeout=10).json()
        sensors = [
            state
            for state in states
            if state["entity_id"].startswith("sensor.")
            and state.get("attributes", {}).get("options") == ["low", "medium", "high"]
        ]
        if sensors and sensors[0]["state"] != "unavailable":
            break
        time.sleep(0.5)
    entity_id = sensors[0]["entity_id"]
    assert instance.ws("vegvesen/route_map", entity_id=entity_id)["geometry"]
    device_id = next(
        entity["device_id"]
        for entity in instance.ws("config/entity_registry/list")
        if entity["entity_id"] == entity_id
    )
    assert instance.ws("vegvesen/route_map", device_id=device_id)["geometry"]
    instance.ws(
        "lovelace/resources/create",
        url="/vegvesen/route-map/vegvesen-route-map.js",
        res_type="module",
    )
    instance.ws(
        "lovelace/dashboards/create",
        url_path="route-test",
        title="Route test",
        mode="storage",
        show_in_sidebar=True,
        require_admin=False,
    )
    instance.ws(
        "lovelace/config/save",
        url_path="route-test",
        config={
            "views": [
                {
                    "title": "Route",
                    "cards": [
                        {"type": "custom:vegvesen-route-map", "entity": entity_id}
                    ],
                }
            ]
        },
    )
    tokens = {
        **instance.tokens,
        "hassUrl": base,
        "clientId": base + "/",
        "expires": time.time() * 1000 + 1800000,
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
        )
        page = browser.new_page(viewport={"width": 390, "height": 844}, has_touch=True)
        page.set_default_timeout(30000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def trace_socket(socket: object) -> None:
            commands = {}

            def sent(payload: str) -> None:
                message = json.loads(payload)
                commands[message.get("id")] = message.get("type")

            def received(payload: str) -> None:
                batch = json.loads(payload)
                for message in batch if isinstance(batch, list) else [batch]:
                    if message.get("error"):
                        print(
                            "Card WS error:",
                            commands.get(message.get("id")),
                            message["error"]["code"],
                        )

            socket.on("framesent", sent)
            socket.on("framereceived", received)

        page.on("websocket", trace_socket)
        page.on(
            "console",
            lambda message: (
                print(message.text)
                if message.text.startswith("Card rejection:")
                else None
            ),
        )
        page.add_init_script("""window.addEventListener('unhandledrejection', event => {
            console.warn('Card rejection:', JSON.stringify(event.reason));
        });""")
        page.add_init_script(
            f"localStorage.setItem('hassTokens', {json.dumps(json.dumps(tokens))});"
        )
        try:
            page.goto(base + "/route-test/0")
            card = page.locator("vegvesen-route-map").first
            expect(card.locator("canvas")).to_be_visible(timeout=30000)
            page.wait_for_function("document.querySelector('home-assistant') !== null")
            expect(card).to_have_js_property("_ready", value=True)
            expect(card.locator(".status")).to_have_text("")
            card.evaluate(
                "async c => { if (!c._map.loaded()) await new Promise("
                "resolve => c._map.once('idle', resolve)); }"
            )
            assert card.evaluate("c => c._map.getSource('forecasts') !== undefined")
            assert (
                card.evaluate(
                    "c => c._map.getStyle().sources['versatiles-shortbread'].type"
                )
                == "vector"
            )
            zoom = card.evaluate("c => c._map.getZoom()")
            card.get_by_role("button", name="Zoom in", exact=True).click()
            page.wait_for_timeout(500)
            assert card.evaluate("c => c._map.getZoom()") > zoom
            before = card.evaluate("c => c._map.getCenter().toArray()")
            canvas = card.locator("canvas")
            box = canvas.bounding_box()
            # Exercise browser touch panning, not a direct map panTo call.
            cdp = page.context.new_cdp_session(page)
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            for kind, offset in (
                ("touchStart", 0),
                ("touchMove", 40),
                ("touchMove", 80),
                ("touchEnd", 80),
            ):
                cdp.send(
                    "Input.dispatchTouchEvent",
                    {
                        "type": kind,
                        "touchPoints": []
                        if kind == "touchEnd"
                        else [{"x": x + offset, "y": y}],
                    },
                )
                page.wait_for_timeout(60)
            assert card.evaluate("c => c._map.getCenter().toArray()") != before
            card.get_by_role("button", name="Fit route", exact=True).click()
            page.wait_for_timeout(1000)
            assert abs(card.evaluate("c => c._map.getZoom()") - zoom) < 0.01
            expect(card.locator(".headline")).to_contain_text(
                "Highest forecast slipperiness:"
            )
            card.locator(".modes").get_by_role(
                "button", name="Slipperiness", exact=True
            ).click()
            chip = card.locator(".legend button:not([disabled])").first
            chip.click()
            expect(chip).to_have_attribute("aria-pressed", "true")
            expect(chip).to_be_focused()
            assert card.evaluate("c => c._selection.mode === 'slip'")
            assert card.evaluate(
                "c => c._map.getStyle().sources.forecasts.data.features.length > 0"
            )
            page.screenshot(path=str(instance.results / "slipperiness-highlight.png"))
            card.get_by_role("button", name="Fit route", exact=True).click()
            assert card.evaluate("c => c._selection === undefined")
            card.locator(".modes").get_by_role(
                "button", name="Road condition", exact=True
            ).click()
            page.screenshot(path=str(instance.results / "mobile-vector-card.png"))
            print(
                "Mobile vector map rendered; zoom, touch pan and fit passed", flush=True
            )
            print("Basemap status:", card.locator(".basemap").inner_text(), flush=True)
            assert not card.locator(".basemap").inner_text()
            # Tap a rendered source segment. Geometry stays in the map, with
            # source values rendered as text in the popup.
            point = card.evaluate("""c => {
                const map = c._map;
                for (const f of map.queryRenderedFeatures({layers: ['forecasts']})) {
                    const lines = f.geometry.type === 'LineString'
                        ? [f.geometry.coordinates] : f.geometry.coordinates;
                    for (const line of lines) for (const coordinate of line) {
                        const p = map.project(coordinate);
                        if (p.x > 50 && p.x < map.getCanvas().clientWidth - 50
                            && p.y > 70 && p.y < map.getCanvas().clientHeight - 70)
                            return p;
                    }
                }
            }""")
            assert point, "Expected a visible source forecast segment"
            canvas.click(position=point)
            expect(card.locator(".popup")).to_be_visible()
            expect(card.locator(".popup")).to_contain_text("Road temperature:")
            page.screenshot(path=str(instance.results / "segment-popup.png"))
            card.locator(".maplibregl-popup-close-button").click()
            # A touch just outside a narrow painted line still opens its data.
            near_line = card.evaluate("""c => {
                const map = c._map;
                for (let x = 60; x < map.getCanvas().clientWidth - 60; x += 4) {
                    for (let y = 80; y < map.getCanvas().clientHeight - 80; y += 4) {
                        const point = [x, y];
                        if (!map.queryRenderedFeatures(point,
                            {layers: ['forecasts']}).length &&
                            map.queryRenderedFeatures(point,
                            {layers: ['forecasts-hit']}).length) return {x, y};
                    }
                }
            }""")
            assert near_line, "Expected a touch target beyond the painted stroke"
            canvas.tap(position=near_line)
            expect(card.locator(".popup")).to_be_visible()
            card.locator(".maplibregl-popup-close-button").click()
            # Capture the same source line at street scales for visual review.
            center = card.evaluate(
                "(c, p) => c._map.unproject([p.x, p.y]).toArray()", point
            )
            for street_zoom in (16, 18):
                card.evaluate(
                    "(c, options) => c._map.jumpTo(options)",
                    {"center": center, "zoom": street_zoom},
                )
                card.evaluate(
                    "async c => { if (!c._map.loaded()) await new Promise("
                    "resolve => c._map.once('idle', resolve)); }"
                )
                page.screenshot(
                    path=str(instance.results / f"mobile-zoom-{street_zoom}.png")
                )
            card.get_by_role("button", name="Fit route", exact=True).click()
            page.locator("home-assistant").evaluate("""element => {
                element.dispatchEvent(new CustomEvent('hass-language-select', {
                    detail: 'nb', bubbles: true, composed: true
                }));
            }""")
            expect(card.get_by_role("button", name="Vis hele ruten")).to_be_visible()
            expect(card.locator(".time")).to_contain_text("Prognosen gjelder for")
            expect(card).to_have_js_property("_ready", value=True)
            card.evaluate(
                "async c => { if (!c._map.loaded()) await new Promise("
                "resolve => c._map.once('idle', resolve)); }"
            )
            page.screenshot(path=str(instance.results / "mobile-nb.png"))
            page.wait_for_timeout(1000)
            page.locator("home-assistant").evaluate("""element => {
                element.dispatchEvent(new CustomEvent('hass-language-select', {
                    detail: 'en', bubbles: true, composed: true
                }));
            }""")
            # An existing sensor-based card opens with the route preselected.
            page.set_viewport_size({"width": 1280, "height": 900})
            page.wait_for_timeout(1000)
            page.reload()
            expect(card.locator("canvas")).to_be_visible(timeout=30000)
            edit = page.get_by_role("button", name="Edit dashboard", exact=True)
            if edit.count():
                edit.click()
            else:
                # HA 2025.12's promoted edit button has a tooltip but no
                # accessible label; identify its actual rendered button.
                tooltip = page.locator("hui-root ha-tooltip").filter(
                    has_text="Edit dashboard"
                )
                button_id = tooltip.evaluate("e => e.for")
                page.locator(f"hui-root ha-icon-button[id='{button_id}']").click()
            page.get_by_role("button", name="Edit", exact=True).first.click()
            dialog = page.locator("hui-dialog-edit-card")
            selector = dialog.locator("ha-selector-device")
            expect(selector).to_be_visible()
            expect(selector).to_have_js_property("label", "Route")
            expect(selector).to_have_js_property("value", device_id)
            expect(selector).to_contain_text("Trondheim - Orkanger")
            assert not dialog.locator("ha-selector-entity").count()
            page.locator("home-assistant").evaluate("""element => {
                element.dispatchEvent(new CustomEvent('hass-language-select', {
                    detail: 'nb', bubbles: true, composed: true
                }));
            }""")
            expect(selector).to_have_js_property("label", "Rute")
            page.screenshot(path=str(instance.results / "card-editor.png"))
            page.locator("home-assistant").evaluate("""element => {
                element.dispatchEvent(new CustomEvent('hass-language-select', {
                    detail: 'en', bubbles: true, composed: true
                }));
            }""")
            expect(selector).to_have_js_property("label", "Route")
            choose_route(selector)
            expect(selector).to_have_js_property("value", device_id)
            dialog.get_by_role("button", name="Save", exact=True).click()
            expect(dialog).not_to_be_visible()
            # Normal editor saving writes the device; no dashboard storage hacks.
            saved = card.evaluate("""c => c._hass.callWS({
                type: 'lovelace/config', url_path: 'route-test'
            })""")
            saved_card = saved["views"][0]["cards"][0]
            assert saved_card["device_id"] == device_id, saved_card
            assert "entity" not in saved_card, saved_card
            page.reload()
            expect(card.locator("canvas")).to_be_visible(timeout=30000)
            assert card.evaluate("c => c._config.device_id") == device_id
            # HA 2025.12 can reject a skipped native view transition on a
            # language change. It is unrelated to card rendering; keep all
            # other uncaught frontend failures fatal.
            unexpected = [
                error
                for error in errors
                if error != "Transition was skipped. New ViewTransition started"
            ]
            assert not unexpected, unexpected
            if errors:
                print("Native frontend transition notices:", errors)
            (instance.results / "result.json").write_text(
                json.dumps(
                    {
                        "entity": entity_id,
                        "device_id": device_id,
                        "legacy_editor_migration": True,
                        "route_picker": True,
                        "version": session.get(base + "/api/config", timeout=10).json()[
                            "version"
                        ],
                        "vector": True,
                        "touch_pan": True,
                        "segment_touch_target": True,
                        "visual_editor": True,
                        "summary_highlight": True,
                        "forecast_hours": 0,
                    },
                    indent=2,
                )
                + "\n"
            )
        except BaseException:
            print("Browser errors:", errors)
            print(page.locator("body").aria_snapshot())
            page.screenshot(path=str(instance.results / "failure.png"))
            raise
        finally:
            browser.close()


def main() -> None:
    """Run one target at a time; always stop HA and remove credentials."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target", choices=["primary", "beta", "minimum"], default="beta"
    )
    args = parser.parse_args()
    python = (
        Path(sys.executable)
        if args.target == "primary"
        else ROOT / f"environments/{args.target}/.venv/bin/python"
    )
    version = json.loads(
        (ROOT / "custom_components/vegvesen/manifest.json").read_text()
    )["version"]
    with TemporaryDirectory(prefix="vegvesen-card-", dir=ROOT / ".tools") as temporary:
        config = Path(temporary)
        with ZipFile(ROOT / ".tools/packages" / f"vegvesen-{version}.zip") as archive:
            archive.extractall(config)
        instance = SmokeInstance(
            config, ROOT / f".tools/card-results-{args.target}", python, 18127
        )
        with (config / "configuration.yaml").open("a") as settings:
            settings.write(
                "lovelace:\n  mode: storage\nrecorder:\n  purge_keep_days: 1\n"
            )
        try:
            instance.start()
            instance.onboard()
            run(instance)
        finally:
            instance.stop()


if __name__ == "__main__":
    handle_termination()
    main()
