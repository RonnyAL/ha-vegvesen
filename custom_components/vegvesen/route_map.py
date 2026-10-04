"""Render route and source segment geometry without inferring road conditions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from .route_geometry import validate_lines

if TYPE_CHECKING:
    from .map_tiles import TileKey
    from .route_coordinator import RouteSnapshot

WIDTH, HEIGHT = 960, 480
TILE_SIZE = 256
MERCATOR_LIMIT = 85.05112878
ROUTE_COLOR = "#174ea6"
UNKNOWN_COLOR = "#777777"
CONDITION_COLORS = {
    "NoNewPrecipitation": "#009e73",
    "WetRoadSurface": "#56b4e9",
    "IceOrFrost": "#e69f00",
    "SnowCover": "#cc79a7",
    "DriftingSnow": "#d55e00",
    "ErrorOrNoData": UNKNOWN_COLOR,
}


@dataclass(frozen=True, slots=True)
class MapContent:
    """One route proposal or one complete forecast snapshot, kept out of state."""

    name: str
    geometry: dict[str, Any]
    snapshot: RouteSnapshot | None = None


@dataclass(frozen=True, slots=True)
class Viewport:
    """One bounded, auto-fitted viewport; disconnected lines remain separate."""

    zoom: int
    left: float
    top: float
    anchor: float
    mercator: bool
    lines: tuple[tuple[tuple[float, float], ...], ...]

    def point(self, longitude: float, latitude: float) -> tuple[float, float]:
        """Project coordinates, with world wrapping around the route's first point."""
        x, y = project(longitude, latitude, mercator=self.mercator)
        x = self.anchor + (x - self.anchor + 0.5) % 1 - 0.5
        scale = TILE_SIZE * 2**self.zoom
        return x * scale - self.left, y * scale - self.top

    def tiles(self) -> dict[tuple[int, int], TileKey]:
        """Only request the single zoom level visible in this image."""
        if not self.mercator:
            return {}
        size = 2**self.zoom
        return {
            (x, y): (self.zoom, x % size, y)
            for x in range(
                math.floor(self.left / TILE_SIZE),
                math.ceil((self.left + WIDTH) / TILE_SIZE),
            )
            for y in range(
                math.floor(self.top / TILE_SIZE),
                math.ceil((self.top + HEIGHT) / TILE_SIZE),
            )
            if 0 <= y < size
        }


def project(
    longitude: float, latitude: float, *, mercator: bool
) -> tuple[float, float]:
    """Use a geographic fallback for polar routes outside the basemap projection."""
    x = (longitude + 180) / 360
    y = (
        (1 - math.asinh(math.tan(math.radians(latitude))) / math.pi) / 2
        if mercator
        else (90 - latitude) / 180
    )
    return x, y


def make_viewport(content: MapContent) -> Viewport:
    """Fit the selected route with padding, not the extent of nearby side roads."""
    lines = validate_lines(content.geometry)
    mercator = all(abs(p[1]) <= MERCATOR_LIMIT for line in lines for p in line)
    anchor = project(*lines[0][0], mercator=mercator)[0]
    points = [project(*point, mercator=mercator) for line in lines for point in line]
    xs = [anchor + (x - anchor + 0.5) % 1 - 0.5 for x, _ in points]
    ys = [y for _, y in points]
    span = max(
        (max(xs) - min(xs)) / (WIDTH - 100), (max(ys) - min(ys)) / (HEIGHT - 100)
    )
    zoom = (
        min(16, max(0, math.floor(math.log2(1 / (TILE_SIZE * span))))) if span else 16
    )
    scale = TILE_SIZE * 2**zoom
    return Viewport(
        zoom,
        (min(xs) + max(xs)) / 2 * scale - WIDTH / 2,
        (min(ys) + max(ys)) / 2 * scale - HEIGHT / 2,
        anchor,
        mercator,
        tuple(tuple(tuple(p) for p in line) for line in lines),
    )


def _draw_basemap(
    view: Viewport, tiles: dict[TileKey, bytes]
) -> tuple[Image.Image, bool]:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), "#eef0f2")
    complete = view.mercator
    for (x, y), key in view.tiles().items():
        try:
            if key not in tiles:
                complete = False
                continue
            with Image.open(BytesIO(tiles[key])) as tile:
                if tile.size != (TILE_SIZE, TILE_SIZE) or tile.format != "PNG":
                    complete = False
                    continue
                canvas.paste(
                    tile.convert("RGB"),
                    (round(x * TILE_SIZE - view.left), round(y * TILE_SIZE - view.top)),
                )
        except (
            UnidentifiedImageError,
            OSError,
            ValueError,
            Image.DecompressionBombError,
        ):
            complete = False
    return canvas, complete


def _draw_lines(canvas: Image.Image, view: Viewport, content: MapContent) -> None:
    draw = ImageDraw.Draw(canvas)
    for line in view.lines:
        points = [view.point(*p) for p in line]
        draw.line(points, fill="white", width=14, joint="curve")
        draw.line(points, fill=ROUTE_COLOR, width=10, joint="curve")
    if content.snapshot:
        for segment in content.snapshot.segments:
            if segment.geometry is None:
                continue
            color = CONDITION_COLORS.get(
                segment.properties.get("ROAD_CONDITION"), UNKNOWN_COLOR
            )
            for line in validate_lines(segment.geometry):
                # Polar source geometry is not representable on a Mercator map.
                if view.mercator and any(abs(p[1]) > MERCATOR_LIMIT for p in line):
                    continue
                draw.line(
                    [view.point(*p) for p in line], fill=color, width=5, joint="curve"
                )
    for label, point in (("A", view.lines[0][0]), ("B", view.lines[-1][-1])):
        x, y = view.point(*point)
        draw.ellipse(
            (x - 14, y - 14, x + 14, y + 14), fill=ROUTE_COLOR, outline="white", width=2
        )
        draw.text(
            (x, y),
            label,
            font=ImageFont.load_default(size=17),
            anchor="mm",
            fill="white",
        )


def _text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    value: str,
    width: int,
    size: int = 18,
) -> None:
    font = ImageFont.load_default(size=size)
    while value and draw.textbbox((0, 0), value, font=font)[2] > width:
        value = value[:-2].rstrip() + "…" if len(value) > 2 else ""  # noqa: PLR2004
    draw.text(xy, value, fill="#242424", font=font)


def render_map(
    content: MapContent,
    view: Viewport,
    tiles: dict[TileKey, bytes],
    labels: dict[str, str],
) -> tuple[bytes, bool]:
    """Generate a PNG off the event loop; colors represent source codes only."""
    basemap, complete = _draw_basemap(view, tiles)
    _draw_lines(basemap, view, content)
    canvas = Image.new(
        "RGB", (WIDTH, HEIGHT + (228 if content.snapshot else 110)), "white"
    )
    canvas.paste(basemap, (0, 42))
    draw = ImageDraw.Draw(canvas)
    # Pillow's bundled font supports Bokmål but not the route-name arrow.
    _text(draw, (16, 10), content.name.replace("→", " / "), WIDTH - 32, 22)
    y = HEIGHT + 52
    _text(draw, (16, y), labels["endpoints"], 450)
    _text(draw, (490, y), "© OpenStreetMap contributors", 460, 16)
    if not complete:
        draw.rectangle((8, 50, 325, 78), fill="white")
        _text(draw, (16, 55), labels["basemap_unavailable"], 300, 16)
    if content.snapshot:
        stamp = content.snapshot.forecast_time.strftime("%Y-%m-%d %H:%M UTC")
        _text(draw, (16, y + 26), f"{labels['forecast_time']}: {stamp}", 900)
        legends = [(ROUTE_COLOR, labels["selected_route"])]
        legends.extend(
            (color, labels[code])
            for code, color in CONDITION_COLORS.items()
            if code != "ErrorOrNoData"
        )
        legends.append((UNKNOWN_COLOR, labels["unknown"]))
        if not content.snapshot.segments:
            legends.append(("white", labels["no_segments"]))
        for index, (color, label) in enumerate(legends):
            x, row = 16 + (index % 2) * 470, y + 54 + (index // 2) * 24
            draw.line((x, row + 9, x + 26, row + 9), fill=color, width=5)
            _text(draw, (x + 36, row), label, 420, 17)
    _text(
        draw,
        (16, canvas.height - 22),
        "Statens vegvesen · openstreetmap.org/copyright",
        900,
        14,
    )
    output = BytesIO()
    canvas.save(output, format="PNG")
    return output.getvalue(), complete
