"""Test the packaged card in a disposable HA and Chromium with public locations."""

import argparse
import base64
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
        mode.get_by_text(option, exact=True).click()
    else:
        mode.get_by_role("combobox").click()
        # Material makes options visible before its opening animation completes.
        # Selecting too early lets its later `opened` event reopen the menu.
        # Wait for the rendered state, without changing native selector state.
        surface = mode.locator("mwc-menu-surface div.mdc-menu-surface")
        expect(surface).to_have_class(re.compile(r"\bmdc-menu-surface--open\b"))
        expect(surface).not_to_have_class(
            re.compile("mdc-menu-surface--animating-open")
        )
        choice = mode.get_by_role("option", name=option, exact=True)
        expect(choice).to_be_visible()
        choice.press("Enter")
        expect(mode.get_by_role("combobox")).to_have_attribute("aria-expanded", "false")
        expect(mode.get_by_role("listbox")).not_to_be_visible()


def presentation_settings(dialog: Locator) -> None:
    """Change each setting using the supported frontend's native controls."""
    dialog.locator("ha-selector-text").get_by_role("textbox").fill("Route overview")
    if not dialog.locator("ha-selector-number input").first.is_visible():
        dialog.get_by_text("Appearance", exact=True).click()
    dialog.locator("ha-selector-number input").first.fill("480")
    select_setting(dialog, "Initial layer", "Slipperiness")
    select_setting(dialog, "Map style", "Natural")
    select_setting(dialog, "Theme mode", "Dark")
    # Native switches can paint a control above their input. Exercise
    # normal keyboard activation instead of clicking through that layer.
    dialog.locator("ha-selector-boolean").first.get_by_role("switch").press("Space")
    dialog.get_by_text("Road cameras", exact=True).click()
    dialog.locator("ha-selector-boolean").nth(1).get_by_role("switch").press("Space")
    dialog.locator("ha-selector-number input").nth(1).fill("350")
    dialog.get_by_text("Weather stations", exact=True).click()
    dialog.locator("ha-selector-boolean").nth(2).get_by_role("switch").press("Space")
    dialog.locator("ha-selector-number input").nth(2).fill("500")
    dialog.get_by_role("button", name="Save", exact=True).click()
    expect(dialog).not_to_be_visible()


def map_controls(card: Locator, *, dark: bool) -> None:
    """Match the native map's boxed zoom and transparent action buttons."""
    zoom = card.get_by_role("button", name="Zoom in", exact=True)
    assert zoom.bounding_box()["width"] == 29
    assert zoom.evaluate("e => getComputedStyle(e.parentElement).backgroundColor") == (
        "rgb(28, 28, 28)" if dark else "rgb(255, 255, 255)"
    )
    for name in ("Fit route", "Expand map", "Map layers and legend"):
        button = card.get_by_role("button", name=name, exact=True)
        assert button.bounding_box()["width"] == 48
        assert button.bounding_box()["height"] == 48
        assert button.evaluate("e => getComputedStyle(e).color") == (
            "rgb(255, 255, 255)" if dark else "rgb(0, 0, 0)"
        )
        assert (
            button.evaluate("e => getComputedStyle(e.parentElement).backgroundColor")
            == "rgba(0, 0, 0, 0)"
        )
        assert button.evaluate("e => getComputedStyle(e).backgroundColor") == (
            "rgba(0, 0, 0, 0)"
        )
        assert (
            button.evaluate("e => getComputedStyle(e.parentElement).boxShadow")
            == "none"
        )


def compare_layers(page: Page, card: Locator, results: Path) -> None:
    """Switch forecast layers at a chosen camera, including after filtering."""
    card.get_by_role("button", name="Zoom in", exact=True).click()
    card.evaluate("""async c => {
        if (c._map.isMoving()) await new Promise(resolve =>
            c._map.once('moveend', resolve));
    }""")
    camera = """c => ({center: c._map.getCenter().toArray(),
        zoom: c._map.getZoom(), bearing: c._map.getBearing(),
        pitch: c._map.getPitch()})"""
    before = card.evaluate(camera)
    initial_colors = card.evaluate(
        "c => c._map.getStyle().sources.forecasts.data.features"
        ".map(f => f.properties._color)"
    )
    modes = card.get_by_role("group", name="Forecast layer", exact=True)
    for label in ("Slipperiness", "Road condition", "Slipperiness"):
        button = modes.get_by_role("button", name=label, exact=True)
        button.press("Enter")
        expect(button).to_have_attribute("aria-pressed", "true")
        expect(button).to_be_focused()
        after = card.evaluate(camera)
        assert after == before, (label, before, after)
    assert (
        card.evaluate(
            "c => c._map.getStyle().sources.forecasts.data.features"
            ".map(f => f.properties._color)"
        )
        != initial_colors
    )
    category = card.locator(".legend button:not([disabled])").first
    category.click()
    selected_camera = card.evaluate(camera)
    modes.get_by_role("button", name="Slipperiness", exact=True).click()
    expect(category).to_have_attribute("aria-pressed", "true")
    assert card.evaluate(camera) == selected_camera
    modes.get_by_role("button", name="Road condition", exact=True).click()
    assert card.evaluate(camera) == selected_camera
    assert card.evaluate("c => c._selection === undefined")
    assert card.evaluate(
        "c => c._map.getStyle().sources.forecasts.data.features.length"
        " === c._snapshot.segments.filter(f => f.geometry).length"
    )
    for button in card.locator(".modes button, .legend button, .panel-close").all():
        if button.is_visible():
            assert button.bounding_box()["height"] >= 44
    assert card.locator(".information").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.screenshot(path=str(results / "forecast-layers.png"))
    card.get_by_role("button", name="Close map layers", exact=True).click()
    expect(card.locator(".legend")).not_to_be_visible()
    expect(card.locator(".information")).not_to_be_visible()
    expect(card.get_by_role("button", name="Map layers and legend")).to_be_focused()
    assert card.evaluate(camera) == selected_camera
    card.get_by_role("button", name="Fit route", exact=True).click()
    card.get_by_role("button", name="Map layers and legend").click()


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
            map_controls(card, dark=mode == "dark")
            # HA leaves the library's attribution light in both map themes.
            assert (
                card.locator(".maplibregl-ctrl-attrib").evaluate(
                    "e => getComputedStyle(e).backgroundColor"
                )
                == "rgb(255, 255, 255)"
            )
            assert (
                card.locator(".maplibregl-ctrl-attrib").evaluate(
                    "e => getComputedStyle(e).color"
                )
                == "rgb(0, 0, 0)"
            )
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
        map_controls(card, dark=mode == "dark")
        page.screenshot(path=str(results / f"auto-{mode}.png"))
    card.evaluate("(c, config) => c.setConfig(config)", {**config, "height": 240})
    expect(card.get_by_role("button", name="Close segment details")).to_be_in_viewport()
    attribution = card.locator(".maplibregl-ctrl-attrib")
    toggle = attribution.locator("summary")
    if not attribution.locator(".maplibregl-ctrl-attrib-inner").is_visible():
        toggle.click()
    credit_box = attribution.bounding_box()
    panel_box = card.locator(".inspector").bounding_box()
    assert panel_box["y"] + panel_box["height"] <= credit_box["y"]
    expect(attribution.get_by_role("link", name="OpenStreetMap")).to_be_in_viewport()
    page.screenshot(path=str(results / "compact-240.png"))
    card.evaluate("(c, config) => c.setConfig(config)", config)
    card.evaluate("c => delete c._testedMap")


def expanded_map(page: Page, card: Locator, results: Path) -> None:
    """Exercise native fullscreen and the library's mobile CSS fallback."""
    viewport = page.viewport_size
    for fallback in (False, True):
        if fallback:
            # Emulate a browser without native fullscreen APIs in this test.
            card.evaluate("""c => {
                c._card.requestFullscreen = undefined;
                c._card.webkitRequestFullscreen = undefined;
                document.exitFullscreen = undefined;
                document.webkitCancelFullScreen = undefined;
            }""")
        else:
            # Chromium cannot resize its window while native fullscreen is open.
            page.set_viewport_size({"width": 1000, "height": 800})
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
        else:
            # Wide maps show inline credit; narrowing restores its toggle.
            attribution = card.locator(".maplibregl-ctrl-attrib")
            expect(attribution).not_to_have_class(re.compile(r"maplibregl-compact"))
            expect(attribution.locator("summary")).not_to_be_visible()
            assert (
                attribution.evaluate("e => getComputedStyle(e).backgroundColor")
                == "rgba(255, 255, 255, 0.5)"
            )
            expect(
                attribution.get_by_role("link", name="OpenStreetMap")
            ).to_be_visible()
            page.screenshot(path=str(results / "attribution-wide.png"))
        page.screenshot(
            path=str(
                results / ("expanded-fallback.png" if fallback else "expanded.png")
            )
        )
        card.get_by_role("button", name="Close expanded map").click()
        expect(
            card.get_by_role("button", name="Expand map", exact=True)
        ).to_be_visible()
        if not fallback:
            page.set_viewport_size(viewport)
            expect(attribution).to_have_class(re.compile(r"maplibregl-compact"))
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
    expect(card.locator(".information")).not_to_be_visible()
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
    # New forecasts and missing-data counts must not reopen the closed panel.
    expect(card.locator(".information")).not_to_be_visible()
    card.get_by_role("button", name="Map layers and legend").click()
    expect(card.locator(".information")).to_be_visible()
    card.locator(".data-quality summary").click()
    expect(card.locator(".quality")).to_contain_text("Unrecognized values: 1")
    card.get_by_role("button", name="Map layers and legend").click()
    card.evaluate("(c, data) => c._data.onData(data)", original)


def camera_layer(page: Page, card: Locator, results: Path) -> None:
    """Check live automatic discovery, then deterministic grouped-source fixtures."""
    original_config = card.evaluate("c => c._config")
    card.evaluate(
        "c => c.setConfig({...c._config, show_cameras: true, show_weather: true})"
    )
    page.wait_for_function(
        """c => c._cameras.snapshot?.cameras?.status === 'ready' &&
        c._cameras.snapshot?.weather?.status === 'ready'""",
        arg=card.element_handle(),
        timeout=45000,
    )
    discovered = card.evaluate("c => c._cameras.snapshot")
    assert len(discovered["cameras"]["items"]) > 0
    assert len(discovered["weather"]["items"]) > 0
    # The smoke instance contains only a route: these sources have no entities.
    assert card.evaluate(
        "c => !Object.keys(c._hass.states).some(id => id.startsWith('camera.'))"
    )
    (results / "discovered-sources.json").write_text(json.dumps(discovered))
    card.evaluate("(c, config) => c.setConfig(config)", original_config)
    card.evaluate(
        """(c, jpeg) => {
        c._cameraTestHass = c._hass;
        c._cameraTestRequests = [];
        c._cameraTestImage = jpeg;
        const g = c._snapshot.geometry;
        const line = g.type === 'LineString' ? g.coordinates : g.coordinates[0];
        const [longitude, latitude] = line[Math.floor(line.length / 2)];
        c._cameraTestStates = {};
        for (const direction of ['north', 'south']) {
            const id = 'camera.map_fixture_' + direction;
            c._cameraTestStates[id] = {
                entity_id: id, state: 'idle',
                attributes: { source_id: 'map_fixture_' + direction,
                    friendly_name: 'Test road camera ' + direction,
                    longitude, latitude, source_availability: 'videoOrImagesAvailable'
                }
            };
        }
        const h = c._cameraTestHass;
        c.hass = {...h, connection: {
            subscribeMessage: async (callback, message) => {
                if (message.type !== 'vegvesen/subscribe_route_sources')
                    return h.connection.subscribeMessage(callback, message);
                c._sourceTestCallback = callback;
                c._cameraTestUpdate(c._cameraTestCurrent ?? c._cameraTestStates);
                return () => {
                    if (c._sourceTestCallback === callback)
                        delete c._sourceTestCallback;
                };
            },
        }, callWS: async (message) => {
            if (message.type !== 'vegvesen/route_camera') return h.callWS(message);
            c._cameraTestRequests.push(message.source_id);
            const state = Object.values(c._cameraTestCurrent).find(
                s => s.attributes.source_id === message.source_id);
            return {camera: {
                availability: state?.attributes.source_availability ?? null},
                content: c._cameraTestImageFailure ? null : jpeg,
                content_type: 'image/jpeg'};
        }};
        c._cameraTestUpdate = (states) => {
            c._cameraTestCurrent = states;
            c._sourceTestCallback?.({data: {geometry: g,
                cameras: {status: 'ready', items: Object.values(states).map(s => ({
                    source_id: s.attributes.source_id, name: s.attributes.friendly_name,
                    longitude: s.attributes.longitude, latitude: s.attributes.latitude,
                    availability: s.attributes.source_availability,
                    orientation: s.attributes.orientation,
                }))}, weather: {status: 'ready', items: c._config.show_weather
                    ? (c._weatherTestItems ?? []) : []}}});
        };
        c._map.jumpTo({center: [longitude, latitude], zoom: 12});
    }""",
        base64.b64encode((ROOT / "tests/fixtures/camera.jpg").read_bytes()).decode(
            "ascii"
        ),
    )
    expect(card.locator(".source-marker")).to_have_count(0)
    assert card.evaluate("c => c._cameraTestRequests.length") == 0
    card.get_by_role("button", name="Map layers and legend").click()
    expect(card.get_by_role("checkbox")).to_have_count(0)
    card.evaluate("c => c.setConfig({...c._config, show_cameras: true})")
    expect(card.locator(".source-marker")).to_have_count(1)
    card.get_by_role("button", name="Close map layers").click()
    marker = card.locator(".source-marker")
    assert marker.bounding_box()["width"] == 44
    offsets = card.evaluate("""c => {
        const rect = c.shadowRoot.querySelector('.source-marker')
            .getBoundingClientRect();
        const canvas = c._map.getCanvas().getBoundingClientRect();
        const a = c._cameraTestStates['camera.map_fixture_north'].attributes;
        const point = c._map.project([a.longitude, a.latitude]);
        return [rect.x + rect.width / 2 - canvas.x - point.x,
            rect.y + rect.height / 2 - canvas.y - point.y];
    }""")
    assert all(abs(offset) <= 1 for offset in offsets), offsets
    camera = card.evaluate("c => [c._map.getCenter().toArray(), c._map.getZoom()]")
    expect(marker.locator(".source-count")).to_have_text("2")
    expect(marker).to_have_attribute("aria-expanded", "false")
    marker.press("Enter")
    bubble = card.locator(".source-bubble")
    expect(bubble).to_be_visible()
    expect(bubble.locator(".source-choice")).to_have_count(2)
    expect(bubble.locator(".source-choice").first).to_be_focused()
    assert card.evaluate("c => c._cameraTestRequests.length") == 0
    card.evaluate("c => c._cameraTestUpdate(structuredClone(c._cameraTestStates))")
    expect(bubble.locator(".source-choice").first).to_be_focused()
    bubble.locator(".source-choice").first.press("Escape")
    expect(bubble).not_to_be_visible()
    expect(marker).to_be_focused()
    marker.press("Enter")
    page.screenshot(path=str(results / "camera-group-mobile.png"))
    bubble.get_by_role("button", name="Test road camera north").press("Enter")
    panel = card.locator(".camera-panel")
    expect(panel).to_be_visible()
    expect(panel.locator(".camera-image")).to_be_visible()
    expect(panel).to_contain_text("Images available")
    assert card.evaluate("c => c._cameraTestRequests.at(-1)") == "map_fixture_north"
    assert (
        card.evaluate("c => [c._map.getCenter().toArray(), c._map.getZoom()]") == camera
    )
    expect(bubble).not_to_be_visible()
    assert card.evaluate("c => c._cameras.sources.collapseTimer === undefined")
    panel.get_by_role("button", name="Close source details").press("Escape")
    expect(bubble).to_be_visible()
    expect(bubble.locator(".source-choice").first).to_be_focused()
    # Focus inside the choices prevents an idle timeout from hiding them.
    page.wait_for_timeout(8200)
    expect(bubble).to_be_visible()
    # An HA state update in the middle of a press must not replace the button.
    bubble.get_by_role("button", name="Test road camera south").hover()
    page.mouse.down()
    card.evaluate("c => c._cameraTestUpdate(structuredClone(c._cameraTestStates))")
    page.mouse.up()
    expect(panel.locator(".camera-image")).to_be_visible()
    expect(panel.locator("h3")).to_have_text("Test road camera south")
    assert card.evaluate("c => c._cameraTestRequests.at(-1)") == "map_fixture_south"
    page.screenshot(path=str(results / "camera-layer-mobile.png"))
    panel.get_by_role("button", name="Close source details").tap()
    page.mouse.move(385, 830)
    expect(bubble).to_be_visible()
    expect(bubble).not_to_be_visible(timeout=12000)
    expect(marker).to_have_attribute("aria-expanded", "false")
    marker.tap()
    bubble.get_by_role("button", name="Test road camera south").tap()
    expect(panel.locator(".camera-image")).to_be_visible()
    card.evaluate("c => {c._cameraTestImageFailure = true; c._cameras.loadImage();}")
    expect(panel).to_contain_text("Image unavailable")
    expect(panel.locator(".camera-image")).not_to_be_visible()
    assert card.evaluate("c => !!c._snapshot && !c._error")
    card.evaluate("c => {c._cameraTestImageFailure = false; c._cameras.loadImage();}")
    expect(panel.locator(".camera-image")).to_be_visible()
    card.evaluate("""c => {
        const states = structuredClone(c._cameraTestStates);
        states['camera.map_fixture_south'].attributes.source_availability =
            'futureStatus';
        c._cameraTestUpdate(states);
        c._cameraTestImageFailure = true;
        c._cameras.loadImage();
    }""")
    expect(panel).to_contain_text("futureStatus")
    expect(panel.locator(".camera-image")).not_to_be_visible()
    card.evaluate("c => {c._cameraTestImageFailure = false; c._cameras.loadImage();}")
    expect(panel.locator(".camera-image")).to_be_visible()
    # Nearby but distinct coordinates share a group at this zoom, then split.
    card.evaluate("""c => {
        c._cameras.close();
        const states = structuredClone(c._cameraTestStates);
        const first = states['camera.map_fixture_north'].attributes;
        const p = c._map.project([first.longitude, first.latitude]);
        const shifted = c._map.unproject([p.x + 20, p.y]);
        Object.assign(states['camera.map_fixture_south'].attributes,
            {longitude: shifted.lng, latitude: shifted.lat});
        c.setConfig({...c._config, camera_distance_m: 2000});
        c._cameraTestUpdate(states);
        c._cameraTestNearby = states;
    }""")
    expect(marker).to_have_count(1)
    expect(marker.locator(".source-count")).to_have_text("2")
    card.evaluate("c => c._map.jumpTo({zoom: 14})")
    expect(marker).to_have_count(2)
    expect(card.locator(".source-cluster")).to_have_count(0)
    marker.first.tap()
    expect(panel.locator(".camera-image")).to_be_visible()
    card.evaluate("c => c.setConfig({...c._config, show_cameras: false})")
    expect(marker).to_have_count(0)
    expect(panel).not_to_be_visible()
    assert card.evaluate("c => !c._cameras.sources.map && !c._cameras.timer")
    card.evaluate("""c => {
        c.setConfig({...c._config, show_cameras: true});
        c._cameraTestUpdate(c._cameraTestStates);
    }""")
    expect(marker).to_have_count(1)
    expect(marker).to_have_attribute("aria-expanded", "false")
    # Rapid taps are disclosure actions, not map double-tap zoom gestures.
    for _ in range(2):
        marker.tap()
    expect(bubble).not_to_be_visible()
    assert card.evaluate("c => c._map.getZoom()") == 14
    marker.tap()
    bubble.get_by_role("button", name="Test road camera south").tap()
    expect(panel.locator(".camera-image")).to_be_visible()
    # Permission loss/removal clears the frame and its refresh timer immediately.
    card.evaluate("c => c._cameraTestUpdate({})")
    expect(panel).not_to_be_visible()
    expect(marker).to_have_count(0)
    assert card.evaluate("c => c._cameras.timer === undefined")
    # One mixed group exposes observations without making image requests.
    card.evaluate("""c => {
        const a = c._cameraTestStates['camera.map_fixture_north'].attributes;
        c._weatherTestItems = [{source_id: 'test-weather', name: 'Test weather station',
            longitude: a.longitude, latitude: a.latitude, air_temperature: 0,
            measurement_time: null}];
        c.setConfig({...c._config, show_weather: true});
        c._cameraTestUpdate(c._cameraTestStates);
    }""")
    expect(marker.locator(".source-count")).to_have_text("3")
    expect(marker).to_have_attribute(
        "aria-label", "Weather stations (1), Road cameras (2)"
    )
    expect(marker.locator(".source-symbols ha-icon")).to_have_count(2)
    expect(marker).to_have_attribute("aria-expanded", "false")
    before = card.evaluate("c => c._cameraTestRequests.length")
    marker.tap()
    expect(bubble.locator(".source-section h4")).to_have_text(
        ["Weather stations (1)", "Road cameras (2)"]
    )
    expect(bubble.locator(".source-choice").first).to_have_text("Test weather station")
    assert card.evaluate("c => c._cameraTestRequests.length") == before
    for choice in bubble.locator(".source-choice").all():
        assert choice.bounding_box()["height"] >= 48
    # All three choices fit at normal card height, regardless of marker position.
    assert bubble.evaluate("e => e.scrollHeight <= e.clientHeight")
    page.screenshot(path=str(results / "mixed-source-group-mobile.png"))
    bubble.get_by_role("button", name="Test weather station").tap()
    expect(panel).to_contain_text("0 °C")
    expect(panel).to_contain_text("Missing data")
    expect(panel.locator(".camera-image")).not_to_be_visible()
    before = card.evaluate("c => c._cameraTestRequests.length")
    for value, expected in [(-999, "-999 °C"), (None, "Missing data")]:
        card.evaluate(
            """(c, value) => {
            c._weatherTestItems[0].air_temperature = value;
            c._cameraTestUpdate(c._cameraTestStates);
        }""",
            value,
        )
        expect(panel.locator(".source-values")).to_contain_text(expected)
    assert card.evaluate("c => c._cameraTestRequests.length") == before
    page.screenshot(path=str(results / "weather-source-mobile.png"))
    panel.get_by_role("button", name="Close source details").press("Escape")
    expect(bubble.get_by_role("button", name="Test weather station")).to_be_focused()
    # A mixed group keeps directions on their own line and remains readable at
    # 320px, in Bokmål and dark mode. Opening a different kind never fits the map.
    viewport = page.viewport_size
    page.set_viewport_size({"width": 320, "height": 844})
    card.evaluate("""c => {
        c.hass = {...c._hass, locale: {...c._hass.locale, language: 'nb'}};
        c.setConfig({...c._config, theme_mode: 'dark'});
        const states = structuredClone(c._cameraTestStates);
        for (const [id, state] of Object.entries(states)) {
            state.attributes.friendly_name = 'Et langt kameranavn ved veikrysset';
            state.attributes.orientation =
                id.endsWith('north') ? 'Mot nord' : 'Mot sør';
        }
        c._cameraTestUpdate(states);
    }""")
    page.wait_for_function(
        "c => c._ready && c._map.loaded()",
        arg=card.element_handle(),
        timeout=30000,
    )
    # Resizing reprojects the marker; reopen if the map closed its popup.
    if not bubble.is_visible():
        marker.tap()
    expect(bubble.locator(".source-section h4")).to_have_text(
        ["Værstasjoner (1)", "Veikameraer (2)"]
    )
    expect(bubble.locator(".source-choice-detail")).to_have_text(
        ["", "Mot nord", "Mot sør"]
    )
    bubble.locator(".source-choice").last.focus()
    expect(bubble.locator(".source-choice").last).to_be_in_viewport()
    content = card.locator(".source-picker")
    assert content.evaluate("e => e.scrollWidth <= e.clientWidth")
    for choice in bubble.locator(".source-choice").all():
        assert choice.evaluate("e => e.scrollWidth <= e.clientWidth")
    camera = card.evaluate("c => [c._map.getCenter().toArray(), c._map.getZoom()]")
    page.screenshot(path=str(results / "mixed-source-group-nb-dark.png"))
    bubble.locator(".source-choice").last.press("Enter")
    expect(panel.locator("h3")).to_have_text(
        "Et langt kameranavn ved veikrysset — Mot sør"
    )
    expect(panel.locator(".camera-image")).to_be_visible()
    assert (
        card.evaluate("c => [c._map.getCenter().toArray(), c._map.getZoom()]") == camera
    )
    panel.get_by_role("button", name="Lukk kildedetaljer").press("Escape")
    expect(bubble.locator(".source-choice").last).to_be_focused()
    card.evaluate("c => c.setConfig({...c._config, height: 240})")
    if not bubble.is_visible():
        marker.tap()
    bubble.locator(".source-choice").last.focus()
    expect(bubble.locator(".source-choice").last).to_be_in_viewport()
    frame = card.locator(".map-frame").bounding_box()
    box = content.bounding_box()
    assert frame["y"] <= box["y"]
    assert box["y"] + box["height"] <= frame["y"] + frame["height"] - 40
    page.screenshot(path=str(results / "mixed-source-group-compact.png"))
    card.evaluate(
        "(c, height) => c.setConfig({...c._config, height})",
        original_config.get("height", 400),
    )
    # Losing camera discovery leaves weather selectable with a single icon.
    card.evaluate("c => c._cameraTestUpdate({})")
    expect(bubble).not_to_be_visible()
    expect(marker.locator(".source-symbols ha-icon")).to_have_count(1)
    expect(marker).not_to_have_attribute("aria-expanded", "true")
    marker.tap()
    expect(panel.locator("h3")).to_have_text("Test weather station")
    card.evaluate(
        """c => {
        c._cameras.close();
        c.hass = {...c._hass, locale: c._cameraTestHass.locale};
    }"""
    )
    page.set_viewport_size(viewport)
    card.evaluate("""c => {
        c._weatherTestItems = [];
        c.setConfig({...c._config, show_weather: false});
    }""")
    # A larger group stays scrollable inside the mobile map, including dark UI.
    card.evaluate("""c => {
        const states = {};
        for (let i = 0; i < 12; i++) {
            const id = 'camera.map_fixture_' + i;
            const state = structuredClone(
                c._cameraTestStates['camera.map_fixture_north']);
            state.entity_id = id;
            Object.assign(state.attributes, {source_id: 'fixture_' + i,
                friendly_name: 'Camera ' + i});
            states[id] = state;
        }
        c.setConfig({...c._config, theme_mode: 'dark'});
        c._cameraTestUpdate(states);
    }""")
    expect(marker.locator(".source-count")).to_have_text("12")
    marker.tap()
    content = card.locator(".source-picker")
    expect(bubble.locator(".source-choice")).to_have_count(12)
    bubble.locator(".source-choice").last.focus()
    expect(bubble.locator(".source-choice").last).to_be_in_viewport()
    frame = card.locator(".map-frame").bounding_box()
    box = content.bounding_box()
    assert frame["y"] <= box["y"]
    assert box["y"] + box["height"] <= frame["y"] + frame["height"]
    assert (
        content.evaluate("e => getComputedStyle(e).backgroundColor")
        == "rgb(28, 28, 28)"
    )
    page.screenshot(path=str(results / "camera-group-dark.png"))
    bubble.get_by_role("button", name="Collapse group").click()
    expect(bubble).not_to_be_visible()
    card.evaluate(
        """(c, config) => {
        c.hass = c._cameraTestHass;
        c.setConfig(config);
        delete c._cameraTestNearby;
        delete c._cameraTestCurrent;
        delete c._sourceTestCallback;
        delete c._weatherTestItems;
        delete c._cameraTestStates;
        delete c._cameraTestUpdate;
        delete c._cameraTestHass;
        c._fitRoute();
    }""",
        original_config,
    )
    # The dark-mode scenario restores the original style asynchronously.
    page.wait_for_function(
        "c => c._ready && c._map.loaded()",
        arg=card.element_handle(),
        timeout=30000,
    )


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
    picker.locator("input[type='text']").fill("Statens vegvesen")
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
            attribution = card.locator(".maplibregl-ctrl-attrib")
            credit = attribution.get_by_role("link", name="OpenStreetMap")
            expect(credit).to_be_visible()
            expect(credit).to_have_attribute(
                "href", "https://www.openstreetmap.org/copyright"
            )
            assert attribution.evaluate("e => getComputedStyle(e).fontSize") == "12px"
            toggle = attribution.locator("summary")
            expect(toggle).to_have_attribute("title", "Map attribution")
            assert toggle.bounding_box()["width"] == 24
            assert toggle.bounding_box()["height"] == 24
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
            expect(credit).not_to_be_visible()
            toggle.click()
            expect(credit).to_be_visible()
            toggle.press("Enter")
            expect(credit).not_to_be_visible()
            toggle.press("Enter")
            expect(credit).to_be_visible()
            page.screenshot(path=str(instance.results / "attribution-mobile.png"))
            card.get_by_role("button", name="Fit route", exact=True).click()
            page.wait_for_timeout(1000)
            assert abs(card.evaluate("c => c._map.getZoom()") - zoom) < 0.01
            expect(card.locator(".information")).not_to_be_visible()
            expect(card.locator("header")).not_to_be_visible()
            assert card.locator("ha-card").bounding_box()["height"] <= 402
            fit = card.get_by_role(
                "button", name="Fit route", exact=True
            ).bounding_box()
            assert fit["x"] - canvas.bounding_box()["x"] < 16
            assert fit["width"] == 48
            assert fit["y"] - canvas.bounding_box()["y"] == 75
            # A dashboard's card surface color must not recolor the zoom group.
            card.evaluate(
                "c => c._card.style.setProperty('--ha-card-background', '#abc')"
            )
            map_controls(card, dark=False)
            card.evaluate("c => c._card.style.removeProperty('--ha-card-background')")
            expect(card.locator(".legend")).not_to_be_visible()
            card.get_by_role("button", name="Map layers and legend").click()
            expect(card.locator(".information")).to_be_visible()
            expect(card.locator(".time")).to_be_visible()
            compare_layers(page, card, instance.results)
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
            camera_layer(page, card, instance.results)
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
            expect(
                dialog.locator("vegvesen-route-map .maplibregl-ctrl-attrib summary")
            ).to_have_attribute("title", "Kartkilder")
            dialog.get_by_text("Utseende", exact=True).click()
            expect(dialog.locator("ha-selector-number").first).to_have_js_property(
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
            assert saved_card["show_cameras"] is True
            assert saved_card["camera_distance_m"] == 350
            assert saved_card["show_weather"] is True
            assert saved_card["weather_distance_m"] == 500
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
                        "automatic_source_discovery": True,
                        "weather_layer": True,
                        "collapsed_source_groups": True,
                        "source_group_timeout_and_keyboard": True,
                        "mixed_source_hierarchy": True,
                        "camera_failure_recovery": True,
                        "category_highlight": True,
                        "layers_panel_on_demand": True,
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
