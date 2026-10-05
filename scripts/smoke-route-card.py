"""Test the packaged card in a disposable HA and Chromium with public locations."""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from playwright.sync_api import Browser, Locator, Page, Route, expect, sync_playwright
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


def select_setting(dialog: Locator, label: str, option: str) -> None:
    """Select a labeled setting on either native form generation."""
    mode = next(
        item
        for item in dialog.locator("ha-selector-select").all()
        if item.evaluate("e => e.label") == label
    )
    if mode.locator("ha-picker-field").count():
        mode.locator("ha-picker-field").click()
    else:
        mode.get_by_role("combobox").click()
    mode.get_by_text(option, exact=True).click()
    if not mode.locator("ha-picker-field").count():
        expect(mode.get_by_role("listbox")).not_to_be_visible()


def presentation_settings(dialog: Locator) -> None:
    """Change each setting using the supported frontend's native controls."""
    dialog.locator("ha-selector-text").get_by_role("textbox").fill("Route overview")
    if not dialog.locator("ha-selector-number input").is_visible():
        dialog.get_by_text("Appearance", exact=True).click()
    dialog.locator("ha-selector-number input").fill("480")
    select_setting(dialog, "Initial layer", "Slipperiness")
    select_setting(dialog, "Map style", "Natural")
    select_setting(dialog, "Theme mode", "Dark")
    # Native switches can paint a control above their input. Exercise
    # normal keyboard activation instead of clicking through that layer.
    dialog.locator("ha-selector-boolean").get_by_role("switch").press("Space")
    dialog.get_by_role("button", name="Save", exact=True).click()
    expect(dialog).not_to_be_visible()


def map_appearance(page: Page, card: Locator, results: Path) -> None:
    """Check every palette, UI contrast and style swaps with a selected segment."""
    config = card.evaluate("c => c._config")
    selected_id = card.evaluate("c => c._segmentId")
    center = card.evaluate("c => c._map.getCenter().toArray()")
    card.evaluate("c => c._testedMap = c._map")
    for preset in ("default", "colorful", "natural", "muted", "gray", "toner"):
        for mode in ("light", "dark"):
            card.evaluate(
                "(c, config) => c.setConfig(config)",
                {**config, "map_style": preset, "theme_mode": mode},
            )
            expect(card).to_have_js_property("_ready", value=True)
            # MapLibre animates paint changes for 300ms after a style loads.
            page.wait_for_timeout(400)
            assert card.evaluate("c => c._map === c._testedMap")
            assert card.evaluate("c => c._map.getCenter().toArray()") == center
            assert card.evaluate("c => c._segmentId") == selected_id
            assert card.evaluate("c => c._map.getStyle().metadata") == {
                "vegvesen:preset": preset,
                "vegvesen:mode": mode,
            }
            assert card.evaluate(
                "c => getComputedStyle(c._inspector).backgroundColor"
            ) == ("rgb(28, 28, 28)" if mode == "dark" else "rgb(255, 255, 255)")
            if preset == "default":
                page.screenshot(path=str(results / f"default-{mode}.png"))
    card.evaluate(
        "(c, config) => c.setConfig(config)", {**config, "theme_mode": "auto"}
    )
    for mode in ("dark", "light"):
        page.emulate_media(color_scheme=mode)
        expect(card).to_have_js_property("_dark", mode == "dark")
        expect(card).to_have_js_property("_ready", value=True)
        page.wait_for_timeout(400)
        assert card.evaluate("c => c._map.getStyle().metadata['vegvesen:mode']") == mode
        assert card.evaluate("c => getComputedStyle(c._inspector).backgroundColor") == (
            "rgb(28, 28, 28)" if mode == "dark" else "rgb(255, 255, 255)"
        )
        assert card.locator(".maplibregl-ctrl-attrib").evaluate(
            "e => getComputedStyle(e).backgroundColor"
        ) == ("rgb(28, 28, 28)" if mode == "dark" else "rgb(255, 255, 255)")
        page.screenshot(path=str(results / f"auto-{mode}.png"))
    card.evaluate("(c, config) => c.setConfig(config)", {**config, "height": 240})
    expect(card.get_by_role("button", name="Close segment details")).to_be_in_viewport()
    page.screenshot(path=str(results / "compact-240.png"))
    card.evaluate("(c, config) => c.setConfig(config)", config)
    card.evaluate("c => delete c._testedMap")


def expanded_map(page: Page, card: Locator, results: Path) -> None:
    """Exercise native fullscreen and the library's mobile CSS fallback."""
    for fallback in (False, True):
        if fallback:
            # Emulate a browser without native fullscreen APIs in this test.
            card.evaluate("""c => {
                c._card.requestFullscreen = undefined;
                c._card.webkitRequestFullscreen = undefined;
                document.exitFullscreen = undefined;
                document.webkitCancelFullScreen = undefined;
            }""")
        card.get_by_role("button", name="Expand map", exact=True).click()
        expect(card.get_by_role("button", name="Close expanded map")).to_be_visible()
        page.wait_for_timeout(300)
        assert card.evaluate("""c => {
            const box = c._card.getBoundingClientRect();
            return Math.abs(box.width - innerWidth) < 2 &&
                Math.abs(box.height - innerHeight) < 2;
        }""")
        if fallback:
            assert card.evaluate(
                "c => c._card.classList.contains('maplibregl-pseudo-fullscreen')"
            )
        page.screenshot(
            path=str(
                results / ("expanded-fallback.png" if fallback else "expanded.png")
            )
        )
        card.get_by_role("button", name="Close expanded map").click()
        expect(
            card.get_by_role("button", name="Expand map", exact=True)
        ).to_be_visible()
        if fallback:
            card.evaluate("""c => {
                delete c._card.requestFullscreen;
                delete c._card.webkitRequestFullscreen;
                delete document.exitFullscreen;
                delete document.webkitCancelFullScreen;
            }""")
    assert card.locator(".map").bounding_box()["height"] == 400
    card.evaluate(
        "async c => { if (!c._map.loaded()) await new Promise("
        "resolve => c._map.once('idle', resolve)); }"
    )


def basemap_recovery(page: Page, card: Locator) -> None:
    """Keep forecasts usable after a refused style and recover on style change."""
    config = card.evaluate("c => c._config")
    center = card.evaluate("c => c._map.getCenter().toArray()")
    url = "https://example.invalid/unavailable-map-style.json"
    page.route(
        url,
        lambda route: route.fulfill(
            status=404,
            body="Missing style",
            headers={"Access-Control-Allow-Origin": "*"},
        ),
    )
    card.evaluate(
        "(c, config) => c.setConfig(config)", {**config, "map_style_url": url}
    )
    expect(card.locator(".basemap")).to_contain_text("could not be loaded")
    expect(card).to_have_js_property("_ready", value=True)
    assert card.evaluate(
        "c => c._map.getStyle().sources.forecasts.data.features.length > 0"
    )
    assert card.evaluate("c => c._map.getCenter().toArray()") == center
    card.evaluate("(c, config) => c.setConfig(config)", config)
    expect(card).to_have_js_property("_ready", value=True)
    expect(card.locator(".basemap")).to_have_text("")
    page.unroute(url)


def inspector_updates(page: Page, card: Locator, results: Path) -> None:
    """Deliver fixture snapshots through the card's normal subscription callback."""
    inspector = card.locator(".inspector")
    expect(inspector).to_be_visible()
    original = card.evaluate("c => c._snapshot")
    selected_id = card.evaluate("c => c._segmentId")
    center = card.evaluate("c => c._map.getCenter().toArray()")
    for temperature, expected in (
        (0, "0 °C"),
        (-123.75, "-123.75 °C"),
        (None, "Missing data"),
    ):
        card.evaluate(
            """(c, value) => {
            const data = structuredClone(c._snapshot);
            const segment = data.segments.find(s => s.id === c._segmentId);
            segment.properties.ROAD_TEMPERATURE = value;
            c._data.onData(data);
        }""",
            temperature,
        )
        expect(inspector).to_contain_text(expected)
        assert card.evaluate("c => c._segmentId") == selected_id
        assert card.evaluate("c => c._map.getCenter().toArray()") == center
        assert (
            card.evaluate("c => c._map.getFilter('segment-outline').at(-1)")
            == selected_id
        )
    card.get_by_role("button", name="Expand map", exact=True).click()
    expect(inspector).to_be_visible()
    expect(
        inspector.get_by_role("button", name="Close segment details")
    ).to_be_in_viewport()
    page.screenshot(path=str(results / "expanded-inspector.png"))
    card.get_by_role("button", name="Close expanded map").click()
    # A missing source cannot leave stale details or a highlighted old segment.
    card.evaluate("""c => {
        const data = structuredClone(c._snapshot);
        data.segments = data.segments.filter(s => s.id !== c._segmentId);
        c._data.onData(data);
    }""")
    expect(inspector).not_to_be_visible()
    assert card.evaluate("c => c._segmentId === undefined")
    card.evaluate("(c, data) => c._data.onData(data)", original)
    # An unavailable subscription clears selected details and forecast geometry.
    card.evaluate(
        """(c, id) => {
        c._segmentId = id;
        c._renderInspector();
        c._data.onReset();
        c._data.onError('unavailable');
    }""",
        selected_id,
    )
    expect(inspector).not_to_be_visible()
    assert (
        card.evaluate("c => c._map.getStyle().sources.forecasts.data.features.length")
        == 0
    )
    expect(card.locator(".status")).to_contain_text("Route unavailable")
    card.evaluate("(c, data) => c._data.onData(data)", original)
    card.evaluate("""c => {
        const data = structuredClone(c._snapshot);
        data.summary.road_condition.missing_segments = 2;
        data.summary.slip_risk.unrecognized_segments = 1;
        c._data.onData(data);
    }""")
    expect(card.locator(".data-hint")).to_have_text("Incomplete data")
    card.locator(".data-hint").click()
    expect(card.locator(".quality")).to_contain_text("Unrecognized values: 1")
    card.get_by_role("button", name="Map layers and legend").click()
    card.evaluate("(c, data) => c._data.onData(data)", original)


def cold_views(browser: Browser, base: str, tokens: dict, results: Path) -> None:
    """Cold storage dashboards must find the automatically registered card."""
    for view, path in (
        ("panel", "route-test/panel"),
        ("sections", "route-test/sections"),
        ("yaml", "route-yaml/0"),
    ):
        context = browser.new_context(viewport={"width": 390, "height": 844})
        context.add_init_script(
            f"localStorage.setItem('hassTokens', {json.dumps(json.dumps(tokens))});"
        )
        page = context.new_page()
        if view == "panel":
            # A warm extra module may arrive before HA's own app. Reproduce
            # that ordering so card/editor registration must wait for HA.
            def delay_app(route: Route) -> None:
                time.sleep(1)
                route.continue_()

            page.route("**/frontend_latest/app.*.js", delay_app)
        try:
            page.goto(f"{base}/{path}")
            expect(page.locator("vegvesen-route-map canvas")).to_be_visible(
                timeout=30000
            )
            assert (
                page.evaluate("""() => window.customCards.filter(
                card => card.type === 'vegvesen-route-map').length""")
                == 1
            )
            page.screenshot(path=str(results / f"cold-{view}.png"))
        except BaseException:
            print(page.locator("body").aria_snapshot())
            page.screenshot(path=str(results / f"failure-{view}.png"))
            raise
        finally:
            context.close()


def automatic_loading_lifecycle(page: Page, base: str, entry_id: str) -> None:
    """Use public APIs to check registration, legacy resources and removal."""

    # This is the same normal WebSocket API used by the frontend and custom cards.
    def ws(command: str, **data: object) -> object:
        return page.locator("home-assistant").evaluate(
            "(element, message) => element.hass.callWS(message)",
            {"type": command, **data},
        )

    assert ws("lovelace/resources") == []
    resource = ws(
        "lovelace/resources/create",
        url="/vegvesen/route-map/vegvesen-route-map.js?v=0.8.0b6",
        res_type="module",
    )
    page.reload()
    expect(page.locator("vegvesen-route-map canvas")).to_be_visible(timeout=30000)
    assert (
        page.evaluate("""() => window.customCards.filter(
        card => card.type === 'vegvesen-route-map').length""")
        == 1
    )
    # Removing the now-unnecessary manual resource leaves the automatic card working.
    ws("lovelace/resources/delete", resource_id=resource["id"])
    response = page.reload()
    assert "/vegvesen/route-map/vegvesen-route-map.js?v=" in response.text(), (
        "Module absent from HA index"
    )
    expect(page.locator("vegvesen-route-map canvas")).to_be_visible(timeout=30000)
    assert ws("lovelace/resources") == []
    ws("config_entries/disable", entry_id=entry_id, disabled_by="user")
    # A fresh page after unloading must no longer load the module.
    page.goto(base + "/config/integrations")
    page.reload()
    expect(page.locator("home-assistant")).to_be_visible()
    assert page.evaluate("customElements.get('vegvesen-route-map') === undefined")
    ws("config_entries/disable", entry_id=entry_id, disabled_by=None)
    # HA includes registered modules in the next frontend page load.
    page.reload()
    page.wait_for_function("customElements.get('vegvesen-route-map') !== undefined")
    page.goto(base + "/route-test/0")
    expect(page.locator("vegvesen-route-map canvas")).to_be_visible(timeout=30000)


def card_picker(page: Page, device_id: str) -> None:
    """Find the bundled card and its route selector through the normal picker."""
    page.get_by_role("button", name="Add card", exact=True).first.click()
    dialog = page.locator("hui-dialog-create-card")
    dialog.get_by_role("tab", name="By card", exact=True).click()
    picker = dialog.locator("hui-card-picker")
    picker.locator("input").fill("Statens vegvesen")
    # HA places a click-capturing overlay above each live preview.
    picker.locator(".card").filter(has_text="Statens vegvesen route map").locator(
        ".overlay"
    ).click()
    editor = page.locator("hui-dialog-edit-card")
    expect(editor.locator("ha-selector-device")).to_be_visible()
    expect(editor.locator("ha-selector-device")).to_have_js_property("value", device_id)
    editor.get_by_role("button", name="Cancel", exact=True).click()
    expect(editor).not_to_be_visible()


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
    entry_id = instance.ws("config_entries/get", domain="vegvesen")[0]["entry_id"]
    assert instance.ws("vegvesen/route_map", device_id=device_id)["geometry"]
    assert instance.ws("lovelace/resources") == []
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
                },
                {
                    "title": "Panel",
                    "path": "panel",
                    "type": "panel",
                    "cards": [
                        {"type": "custom:vegvesen-route-map", "device_id": device_id}
                    ],
                },
                {
                    "title": "Sections",
                    "path": "sections",
                    "type": "sections",
                    "sections": [
                        {
                            "type": "grid",
                            "cards": [
                                {
                                    "type": "custom:vegvesen-route-map",
                                    "device_id": device_id,
                                }
                            ],
                        }
                    ],
                },
            ]
        },
    )
    # YAML dashboards use the same automatic module registration.
    (instance.config / "route-map.yaml").write_text(
        json.dumps(
            {
                "views": [
                    {
                        "title": "Route",
                        "cards": [
                            {
                                "type": "custom:vegvesen-route-map",
                                "device_id": device_id,
                            }
                        ],
                    }
                ]
            }
        )
    )
    # Test normal HA startup with an existing entry, not only live flow creation.
    instance.stop()
    instance.start()
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
        page.on(
            "pageerror", lambda error: (errors.append(str(error)), print(error.stack))
        )

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
                if message.text.startswith("Card rejection:") or message.type == "error"
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
            expect(card.locator(".headline")).to_contain_text("Highest slipperiness:")
            expect(card.locator("header")).not_to_be_visible()
            assert card.locator("ha-card").bounding_box()["height"] <= 402
            fit = card.get_by_role(
                "button", name="Fit route", exact=True
            ).bounding_box()
            assert fit["x"] - canvas.bounding_box()["x"] < 16
            assert fit["width"] == 32
            expect(card.locator(".legend")).not_to_be_visible()
            card.get_by_role("button", name="Map layers and legend").click()
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
            card.get_by_role("button", name="Map layers and legend").click()
            page.screenshot(path=str(instance.results / "mobile-vector-card.png"))
            print(
                "Mobile vector map rendered; zoom, touch pan and fit passed", flush=True
            )
            print("Basemap status:", card.locator(".basemap").inner_text(), flush=True)
            assert not card.locator(".basemap").inner_text()
            expanded_map(page, card, instance.results)
            # Tap a rendered source segment. Geometry stays in the map, with
            # source values rendered as text in a panel within the map.
            point = card.evaluate("""c => {
                const map = c._map;
                const canvas = map.getCanvas();
                const box = canvas.getBoundingClientRect();
                for (const f of map.queryRenderedFeatures({layers: ['forecasts']})) {
                    const lines = f.geometry.type === 'LineString'
                        ? [f.geometry.coordinates] : f.geometry.coordinates;
                    for (const line of lines) for (const coordinate of line) {
                        const p = map.project(coordinate);
                        if (p.x > 50 && p.x < map.getCanvas().clientWidth - 50
                            && p.y > 70 && p.y < map.getCanvas().clientHeight - 70
                            && c.shadowRoot.elementFromPoint(
                                box.left + p.x, box.top + p.y) === canvas)
                            return p;
                    }
                }
            }""")
            assert point, "Expected a visible source forecast segment"
            canvas.click(position=point)
            expect(card.locator(".inspector")).to_be_visible()
            expect(card.locator(".inspector")).to_contain_text("Road temperature")
            assert (
                card.locator(".inspector").bounding_box()["y"]
                >= canvas.bounding_box()["y"]
            )
            assert card.locator("ha-card").bounding_box()["height"] <= 402
            page.screenshot(path=str(instance.results / "segment-inspector.png"))
            map_appearance(page, card, instance.results)
            inspector_updates(page, card, instance.results)
            # A touch just outside a narrow painted line still opens its data.
            near_line = card.evaluate("""c => {
                const map = c._map;
                const canvas = map.getCanvas();
                const box = canvas.getBoundingClientRect();
                for (let x = 60; x < map.getCanvas().clientWidth - 60; x += 4) {
                    for (let y = 80; y < map.getCanvas().clientHeight - 80; y += 4) {
                        const point = [x, y];
                        if (!map.queryRenderedFeatures(point,
                            {layers: ['forecasts']}).length &&
                            map.queryRenderedFeatures(point,
                            {layers: ['forecasts-hit']}).length &&
                            c.shadowRoot.elementFromPoint(
                                box.left + x, box.top + y) === canvas) return {x, y};
                    }
                }
            }""")
            assert near_line, "Expected a touch target beyond the painted stroke"
            canvas.tap(position=near_line)
            expect(card.locator(".inspector")).to_be_visible()
            card.get_by_role("button", name="Close segment details").click()
            expect(card.locator(".inspector")).not_to_be_visible()
            basemap_recovery(page, card)
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
            expect(card.locator(".time")).to_have_attribute(
                "title", re.compile("Prognosen gjelder for")
            )
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
            card_picker(page, device_id)
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
            dialog.get_by_text("Utseende", exact=True).click()
            expect(dialog.locator("ha-selector-number")).to_have_js_property(
                "label", "Karthøyde"
            )
            expect(dialog.locator("ha-selector-select").nth(2)).to_have_js_property(
                "label", "Kartlag ved åpning"
            )
            page.screenshot(path=str(instance.results / "card-editor.png"))
            page.locator("home-assistant").evaluate("""element => {
                element.dispatchEvent(new CustomEvent('hass-language-select', {
                    detail: 'en', bubbles: true, composed: true
                }));
            }""")
            expect(selector).to_have_js_property("label", "Route")
            choose_route(selector)
            expect(selector).to_have_js_property("value", device_id)
            presentation_settings(dialog)
            # Normal editor saving writes the device; no dashboard storage hacks.
            saved = card.evaluate("""c => c._hass.callWS({
                type: 'lovelace/config', url_path: 'route-test'
            })""")
            saved_card = saved["views"][0]["cards"][0]
            assert saved_card["device_id"] == device_id, saved_card
            assert "entity" not in saved_card, saved_card
            assert saved_card["title"] == "Route overview"
            assert saved_card["height"] == 480
            assert saved_card["default_mode"] == "slip"
            assert saved_card["legend_expanded"] is True
            assert saved_card["theme_mode"] == "dark"
            assert saved_card["map_style"] == "natural"
            for _ in range(3):
                page.reload()
                expect(card.locator("canvas")).to_be_visible(timeout=30000)
                assert card.evaluate("c => c._config.device_id") == device_id
                expect(card.locator("h2")).to_have_text("Route overview")
                assert card.locator(".map").bounding_box()["height"] == 480
                expect(
                    card.locator(".modes").get_by_role("button", name="Slipperiness")
                ).to_have_attribute("aria-pressed", "true")
                expect(card.locator(".legend")).to_be_visible()
                expect(card).to_have_js_property("_dark", value=True)
            cold_views(browser, base, tokens, instance.results)
            automatic_loading_lifecycle(page, base, entry_id)
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
                        "expanded_map": True,
                        "fullscreen_css_fallback": True,
                        "persistent_segment_details": True,
                        "visual_presentation_settings": True,
                        "map_styles": [
                            "default",
                            "colorful",
                            "natural",
                            "muted",
                            "gray",
                            "toner",
                        ],
                        "theme_modes": ["auto", "light", "dark"],
                        "compact_map_controls": True,
                        "forecast_hours": 0,
                        "automatic_registration": True,
                        "card_picker": True,
                        "cold_views": ["masonry", "panel", "sections", "yaml"],
                        "manual_resource_coexistence": True,
                        "unload_and_reregistration": True,
                    },
                    indent=2,
                )
                + "\n"
            )
        except BaseException:
            print("Browser errors:", errors)
            print(
                "Module diagnostics:",
                page.evaluate("""() => ({
                    defined: !!customElements.get('vegvesen-route-map'),
                    resources: performance.getEntriesByType('resource')
                        .filter(r => r.name.includes('/vegvesen/route-map/'))
                        .map(r => ({url: r.name, start: r.startTime,
                            duration: r.duration, size: r.transferSize})),
                    registered: window.customCards?.filter(
                        c => c.type === 'vegvesen-route-map').length
                })"""),
            )
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
                "lovelace:\n  mode: storage\n  dashboards:\n"
                "    route-yaml:\n      mode: yaml\n      title: Route YAML\n"
                "      filename: route-map.yaml\n      show_in_sidebar: false\n"
                "recorder:\n  purge_keep_days: 1\nenergy:\n"
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
