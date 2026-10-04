"""Render route geometry for configuration previews."""

from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from .route_geometry import validate_lines

if TYPE_CHECKING:
    from .map_tiles import TileKey

WIDTH, HEIGHT = 960, 480
# Leave room for endpoint circles above the in-map attribution.
PADDING = 36
TILE_SIZE = 256
BACKGROUND = "#eef0f2"
MERCATOR_LIMIT = 85.05112878
ROUTE_COLOR = "#174ea6"


@dataclass(frozen=True, slots=True)
class MapContent:
    """One route proposal, kept out of entity state."""

    name: str
    geometry: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Viewport:
    """One bounded, auto-fitted viewport; disconnected lines remain separate."""

    zoom: float
    left: float
    top: float
    anchor: float
    mercator: bool
    lines: tuple[tuple[tuple[float, float], ...], ...]

    @property
    def tile_zoom(self) -> int:
        """Use one integer tile level, enlarged to the exact fitted scale."""
        return math.floor(self.zoom)

    @property
    def tile_scale(self) -> float:
        """Scale raster tiles without rounding the route's fitted zoom down."""
        return 2 ** (self.zoom - self.tile_zoom)

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
        size = 2**self.tile_zoom
        scale = TILE_SIZE * self.tile_scale
        return {
            (x, y): (self.tile_zoom, x % size, y)
            for x in range(
                math.floor(self.left / scale),
                math.ceil((self.left + WIDTH) / scale),
            )
            for y in range(
                math.floor(self.top / scale),
                math.ceil((self.top + HEIGHT) / scale),
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
        (max(xs) - min(xs)) / (WIDTH - 2 * PADDING),
        (max(ys) - min(ys)) / (HEIGHT - 2 * PADDING),
    )
    zoom = min(16, max(0, math.log2(1 / (TILE_SIZE * span)))) if span else 16
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
    requested = view.tiles()
    if not requested:
        return Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND), False
    # Resample a single mosaic, avoiding seams from separately resized tiles.
    min_x, min_y = (min(p[i] for p in requested) for i in (0, 1))
    max_x, max_y = (max(p[i] for p in requested) for i in (0, 1))
    mosaic = Image.new(
        "RGB",
        ((max_x - min_x + 1) * TILE_SIZE, (max_y - min_y + 1) * TILE_SIZE),
        BACKGROUND,
    )
    complete = view.mercator
    for (x, y), key in requested.items():
        try:
            if key not in tiles:
                complete = False
                continue
            with Image.open(BytesIO(tiles[key])) as tile:
                if tile.size != (TILE_SIZE, TILE_SIZE) or tile.format != "PNG":
                    complete = False
                    continue
                mosaic.paste(
                    tile.convert("RGB"),
                    ((x - min_x) * TILE_SIZE, (y - min_y) * TILE_SIZE),
                )
        except (
            UnidentifiedImageError,
            OSError,
            ValueError,
            Image.DecompressionBombError,
        ):
            complete = False
    scale = view.tile_scale
    return mosaic.transform(
        (WIDTH, HEIGHT),
        Image.Transform.AFFINE,
        (
            1 / scale,
            0,
            view.left / scale - min_x * TILE_SIZE,
            0,
            1 / scale,
            view.top / scale - min_y * TILE_SIZE,
        ),
        resample=Image.Resampling.BICUBIC,
        fillcolor=BACKGROUND,
    ), complete


def _line_width(zoom: float) -> int:
    """Approximate the card's main-road widths at the 256-pixel raster scale."""
    stops = ((7, 1.25), (11, 2.5), (15, 5), (17, 10))
    for (start, narrow), (end, wide) in pairwise(stops):
        if zoom <= end:
            return max(
                1,
                round(narrow + (wide - narrow) * max(0, zoom - start) / (end - start)),
            )
    return round(stops[-1][1])


def _draw_lines(canvas: Image.Image, view: Viewport) -> None:
    """Draw the route and its endpoints."""
    draw = ImageDraw.Draw(canvas)
    width = _line_width(view.zoom)
    for line in view.lines:
        points = [view.point(*p) for p in line]
        draw.line(points, fill="white", width=width + 2, joint="curve")
        draw.line(points, fill=ROUTE_COLOR, width=width + 1, joint="curve")
    for label, point in (("A", view.lines[0][0]), ("B", view.lines[-1][-1])):
        x, y = view.point(*point)
        draw.ellipse(
            (x - 12, y - 12, x + 12, y + 12), fill=ROUTE_COLOR, outline="white", width=2
        )
        font = ImageFont.load_default(size=15)
        left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
        draw.text(
            (x - (left + right) / 2, y - (top + bottom) / 2),
            label,
            font=font,
            fill="white",
        )


def render_map(
    view: Viewport,
    tiles: dict[TileKey, bytes],
    labels: dict[str, str],
) -> tuple[bytes, bool]:
    """Generate a route-preview PNG off the event loop."""
    basemap, complete = _draw_basemap(view, tiles)
    _draw_lines(basemap, view)
    draw = ImageDraw.Draw(basemap)
    draw.text(
        (WIDTH - 8, HEIGHT - 8),
        "Statens vegvesen · © OpenStreetMap contributors · openstreetmap.org/copyright",
        font=ImageFont.load_default(size=14),
        anchor="rb",
        fill="#242424",
        stroke_width=2,
        stroke_fill="white",
    )
    if not complete:
        draw.text(
            (8, 8),
            labels["basemap_unavailable"],
            font=ImageFont.load_default(size=16),
            anchor="lt",
            fill="#242424",
            stroke_width=2,
            stroke_fill="white",
        )
    output = BytesIO()
    basemap.save(output, format="PNG")
    return output.getvalue(), complete
