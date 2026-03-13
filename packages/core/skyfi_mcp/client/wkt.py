"""GeoJSON <-> WKT conversion utilities for the SkyFi Platform API.

The SkyFi API uses WKT (Well-Known Text) for geometry parameters,
while the MCP tool interface uses GeoJSON.  These helpers bridge the gap.
"""

from __future__ import annotations

from typing import Any


def geojson_to_wkt(geom: dict[str, Any], *, point_buffer_deg: float = 0.05) -> str:
    """Convert a GeoJSON geometry dict to a WKT string.

    Supports Point, Polygon, and MultiPolygon geometry types.
    For Point geometries, creates a small bounding-box polygon around the
    point (default ~5 km buffer) since the SkyFi API requires polygon AOIs.
    """
    geom_type = geom["type"]
    coords = geom["coordinates"]

    if geom_type == "Point":
        lon, lat = coords[0], coords[1]
        d = point_buffer_deg
        # Create a small bounding-box polygon around the point
        ring = [
            [lon - d, lat - d],
            [lon + d, lat - d],
            [lon + d, lat + d],
            [lon - d, lat + d],
            [lon - d, lat - d],
        ]
        return f"POLYGON({_encode_rings([ring])})"

    if geom_type == "Polygon":
        return f"POLYGON({_encode_rings(coords)})"

    if geom_type == "MultiPolygon":
        polys = ",".join(f"({_encode_rings(polygon)})" for polygon in coords)
        return f"MULTIPOLYGON({polys})"

    raise ValueError(f"Unsupported geometry type for WKT conversion: {geom_type}")


def wkt_to_geojson(wkt: str) -> dict[str, Any]:
    """Convert a WKT geometry string to a GeoJSON geometry dict.

    Supports POINT, POLYGON, and MULTIPOLYGON.
    """
    wkt = wkt.strip()
    upper = wkt.upper()

    if upper.startswith("POINT"):
        inner = wkt[wkt.index("(") + 1 : wkt.rindex(")")]
        parts = inner.strip().split()
        return {"type": "Point", "coordinates": [float(parts[0]), float(parts[1])]}

    if upper.startswith("MULTIPOLYGON"):
        return _parse_multipolygon(wkt)

    if upper.startswith("POLYGON"):
        return _parse_polygon(wkt)

    raise ValueError(f"Unsupported WKT geometry: {wkt[:60]}...")


# ---- internal helpers -------------------------------------------------------


def _encode_rings(rings: list[list[list[float]]]) -> str:
    """Encode polygon rings as WKT coordinate lists."""
    parts = []
    for ring in rings:
        points = ",".join(f"{c[0]} {c[1]}" for c in ring)
        parts.append(f"({points})")
    return ",".join(parts)


def _parse_coord_pairs(text: str) -> list[list[float]]:
    """Parse a comma-separated list of 'x y' pairs into [[x,y], ...]."""
    points = []
    for pair in text.split(","):
        pair = pair.strip()
        if not pair:
            continue
        parts = pair.split()
        points.append([float(parts[0]), float(parts[1])])
    return points


def _parse_polygon(wkt: str) -> dict[str, Any]:
    """Parse ``POLYGON((x y,...),(x y,...))``."""
    body = wkt[wkt.index("((") + 2 : wkt.rindex("))")]
    rings_strs = body.split("),(")
    coordinates = [_parse_coord_pairs(rs) for rs in rings_strs]
    return {"type": "Polygon", "coordinates": coordinates}


def _parse_multipolygon(wkt: str) -> dict[str, Any]:
    """Parse ``MULTIPOLYGON(((x y,...)),((x y,...)))``."""
    body = wkt[wkt.index("(((") + 3 : wkt.rindex(")))")].strip()
    polygon_strs = body.split(")),((")
    polygons = []
    for ps in polygon_strs:
        ring_strs = ps.split("),(")
        rings = [_parse_coord_pairs(rs) for rs in ring_strs]
        polygons.append(rings)
    return {"type": "MultiPolygon", "coordinates": polygons}
