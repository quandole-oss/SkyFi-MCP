"""
Static map rendering utility.

Renders OSM-based static map images with polygon overlays for embedding
in MCP responses.  Uses the ``staticmap`` library for tile fetching and
stitching, running the synchronous render in an executor to stay non-blocking.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import sys
from typing import Any

from skyfi_mcp.thumbnails import FetchedThumbnail

logger = logging.getLogger(__name__)


def _extract_outer_ring(geometry: dict[str, Any]) -> list[list[float]] | None:
    """Extract the outer ring coordinates from a Polygon or MultiPolygon."""
    geom_type = geometry.get("type", "")
    coords = geometry.get("coordinates", [])

    if geom_type == "Polygon" and coords:
        return coords[0]
    if geom_type == "MultiPolygon" and coords:
        return coords[0][0]  # first polygon, outer ring
    return None


def _compute_zoom(ring: list[list[float]], width: int, height: int) -> int:
    """Auto-compute a reasonable zoom level from a bounding box."""
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    lon_span = max_lon - min_lon
    lat_span = max_lat - min_lat

    if lon_span <= 0 or lat_span <= 0:
        return 14

    # Approximate zoom from the span
    for zoom in range(18, 0, -1):
        tiles_x = lon_span / (360.0 / (2**zoom))
        tiles_y = lat_span / (180.0 / (2**zoom))
        pixel_x = tiles_x * 256
        pixel_y = tiles_y * 256
        if pixel_x < width * 0.8 and pixel_y < height * 0.8:
            return zoom
    return 1


def _render_map_sync(
    ring: list[list[float]],
    width: int,
    height: int,
) -> bytes:
    """Synchronous render — meant to run in an executor."""
    from staticmap import Polygon, StaticMap

    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    center_lon = (min(lons) + max(lons)) / 2
    center_lat = (min(lats) + max(lats)) / 2
    zoom = _compute_zoom(ring, width, height)

    m = StaticMap(
        width,
        height,
        url_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        headers={"User-Agent": "SkyFi-MCP/1.0"},
        tile_request_timeout=3,
    )

    # Close the ring if not already closed
    closed_ring = list(ring)
    if closed_ring[0] != closed_ring[-1]:
        closed_ring.append(closed_ring[0])

    polygon = Polygon(
        [(lon, lat) for lon, lat in closed_ring],
        fill_color=(0, 100, 255, 80),
        outline_color="blue",
    )
    m.add_polygon(polygon)

    # Redirect stdout to devnull during render to prevent staticmap's
    # print() calls from corrupting the MCP stdio transport.
    old_stdout = sys.stdout
    try:
        sys.stdout = open(os.devnull, "w")
        image = m.render(zoom=zoom, center=[center_lon, center_lat])
    finally:
        sys.stdout.close()
        sys.stdout = old_stdout

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


async def fetch_static_map(
    geometry: dict[str, Any],
    width: int = 600,
    height: int = 400,
    timeout_seconds: float = 8.0,
) -> FetchedThumbnail | None:
    """Render a static map image from a GeoJSON geometry dict.

    Args:
        geometry: GeoJSON geometry (Polygon or MultiPolygon).
        width: Image width in pixels.
        height: Image height in pixels.
        timeout_seconds: Maximum time for rendering.

    Returns:
        FetchedThumbnail with PNG bytes, or None on any failure.
    """
    try:
        ring = _extract_outer_ring(geometry)
        if not ring or len(ring) < 3:
            return None

        loop = asyncio.get_running_loop()
        png_bytes = await asyncio.wait_for(
            loop.run_in_executor(None, _render_map_sync, ring, width, height),
            timeout=timeout_seconds,
        )
        return FetchedThumbnail(data=png_bytes, format="png")
    except Exception:
        logger.debug("Failed to render static map", exc_info=True)
        return None
