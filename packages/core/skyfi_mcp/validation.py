"""
Input validation and sanitization helpers for the SkyFi MCP server.

Provides:
- GeoJSON geometry validation (type, coordinate range, finiteness)
- Overpass QL string sanitization (prevents injection attacks)
- Input length/size limit enforcement
"""

from __future__ import annotations

import math
import re
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Limits
MAX_ADDRESS_LENGTH = 500
MAX_AREA_NAME_LENGTH = 200
MAX_ARRAY_ITEMS = 100
MAX_STRING_INPUT_LENGTH = 1000

# Valid GeoJSON geometry types
_VALID_GEOJSON_TYPES = frozenset({
    "Point",
    "MultiPoint",
    "LineString",
    "MultiLineString",
    "Polygon",
    "MultiPolygon",
    "GeometryCollection",
})

# Valid latitude range
_LAT_MIN, _LAT_MAX = -90.0, 90.0
# Valid longitude range
_LON_MIN, _LON_MAX = -180.0, 180.0


# ---------------------------------------------------------------------------
# GeoJSON validation
# ---------------------------------------------------------------------------


class ValidationError(ValueError):
    """Raised when input validation fails."""


def _is_finite(value: Any) -> bool:
    """Check that a numeric value is finite (not NaN, not Infinity)."""
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _validate_coordinate(coord: list[Any] | tuple[Any, ...], path: str = "") -> None:
    """Validate a single [lon, lat] or [lon, lat, alt] coordinate pair."""
    if not isinstance(coord, (list, tuple)):
        raise ValidationError(f"Coordinate at {path} must be an array, got {type(coord).__name__}")
    if len(coord) < 2:
        raise ValidationError(f"Coordinate at {path} must have at least 2 elements (lon, lat)")
    if len(coord) > 3:
        raise ValidationError(f"Coordinate at {path} has too many elements ({len(coord)})")

    lon, lat = coord[0], coord[1]
    if not _is_finite(lon):
        raise ValidationError(f"Longitude at {path} is not a finite number: {lon!r}")
    if not _is_finite(lat):
        raise ValidationError(f"Latitude at {path} is not a finite number: {lat!r}")
    if lon < _LON_MIN or lon > _LON_MAX:
        raise ValidationError(f"Longitude at {path} out of range [{_LON_MIN}, {_LON_MAX}]: {lon}")
    if lat < _LAT_MIN or lat > _LAT_MAX:
        raise ValidationError(f"Latitude at {path} out of range [{_LAT_MIN}, {_LAT_MAX}]: {lat}")

    # Altitude (optional third element) must also be finite
    if len(coord) == 3:
        alt = coord[2]
        if not _is_finite(alt):
            raise ValidationError(f"Altitude at {path} is not a finite number: {alt!r}")


def _validate_coordinate_ring(ring: list[Any], path: str = "") -> None:
    """Validate a linear ring (array of coordinates)."""
    if not isinstance(ring, (list, tuple)):
        raise ValidationError(f"Coordinate ring at {path} must be an array")
    if len(ring) > MAX_ARRAY_ITEMS * 100:
        raise ValidationError(f"Coordinate ring at {path} has too many points ({len(ring)})")
    for i, coord in enumerate(ring):
        _validate_coordinate(coord, path=f"{path}[{i}]")


def validate_geojson_geometry(geometry: Any) -> None:
    """Validate a GeoJSON geometry object.

    Checks that:
    - ``type`` is a valid GeoJSON geometry type
    - All coordinates are finite numbers within valid lat/lon ranges
    - The coordinate structure matches the geometry type

    Raises
    ------
    ValidationError
        If the geometry fails validation.
    """
    if geometry is None:
        return

    # Support both dicts and Pydantic models
    if hasattr(geometry, "type") and hasattr(geometry, "coordinates"):
        geo_type = geometry.type
        coordinates = geometry.coordinates
    elif isinstance(geometry, dict):
        geo_type = geometry.get("type")
        coordinates = geometry.get("coordinates")
    else:
        raise ValidationError(f"Geometry must be a dict or object with type/coordinates, got {type(geometry).__name__}")

    if geo_type not in _VALID_GEOJSON_TYPES:
        raise ValidationError(
            f"Invalid GeoJSON geometry type: {geo_type!r}. "
            f"Must be one of: {', '.join(sorted(_VALID_GEOJSON_TYPES))}"
        )

    if geo_type == "GeometryCollection":
        # GeometryCollection uses 'geometries' instead of 'coordinates'
        return

    if coordinates is None:
        raise ValidationError(f"Geometry of type {geo_type} must have coordinates")

    if geo_type == "Point":
        _validate_coordinate(coordinates, path="coordinates")

    elif geo_type == "MultiPoint":
        if not isinstance(coordinates, (list, tuple)):
            raise ValidationError("MultiPoint coordinates must be an array")
        for i, coord in enumerate(coordinates):
            _validate_coordinate(coord, path=f"coordinates[{i}]")

    elif geo_type == "LineString":
        _validate_coordinate_ring(coordinates, path="coordinates")

    elif geo_type == "MultiLineString":
        if not isinstance(coordinates, (list, tuple)):
            raise ValidationError("MultiLineString coordinates must be an array of arrays")
        for i, ring in enumerate(coordinates):
            _validate_coordinate_ring(ring, path=f"coordinates[{i}]")

    elif geo_type == "Polygon":
        if not isinstance(coordinates, (list, tuple)):
            raise ValidationError("Polygon coordinates must be an array of rings")
        for i, ring in enumerate(coordinates):
            _validate_coordinate_ring(ring, path=f"coordinates[{i}]")

    elif geo_type == "MultiPolygon":
        if not isinstance(coordinates, (list, tuple)):
            raise ValidationError("MultiPolygon coordinates must be an array of polygons")
        for i, polygon in enumerate(coordinates):
            if not isinstance(polygon, (list, tuple)):
                raise ValidationError(f"MultiPolygon coordinates[{i}] must be an array of rings")
            for j, ring in enumerate(polygon):
                _validate_coordinate_ring(ring, path=f"coordinates[{i}][{j}]")


# ---------------------------------------------------------------------------
# Overpass QL sanitization
# ---------------------------------------------------------------------------

# Characters that have special meaning in Overpass QL and must be escaped
# or stripped from user-supplied values interpolated into queries.
_OVERPASS_DANGEROUS_CHARS = re.compile(r'["\\\';()\[\]{}]')


def sanitize_overpass_value(value: str) -> str:
    """Sanitize a string for safe interpolation into an Overpass QL query.

    - Removes characters that could alter query structure:
      quotes, backslashes, semicolons, parentheses, brackets, braces
    - Enforces a maximum length
    - Strips leading/trailing whitespace

    Parameters
    ----------
    value:
        User-supplied string to sanitize (e.g., a place name).

    Returns
    -------
    str
        The sanitized string, safe for interpolation into Overpass QL
        value positions (inside double-quoted strings).

    Raises
    ------
    ValidationError
        If the value is empty after sanitization or exceeds length limits.
    """
    if not isinstance(value, str):
        raise ValidationError(f"Expected a string, got {type(value).__name__}")

    value = value.strip()

    if len(value) > MAX_AREA_NAME_LENGTH:
        raise ValidationError(
            f"Area name too long ({len(value)} chars, max {MAX_AREA_NAME_LENGTH})"
        )

    # Remove dangerous characters
    sanitized = _OVERPASS_DANGEROUS_CHARS.sub("", value)

    # Collapse any resulting double/triple spaces
    sanitized = re.sub(r"\s+", " ", sanitized).strip()

    if not sanitized:
        raise ValidationError("Area name is empty after sanitization")

    return sanitized


# ---------------------------------------------------------------------------
# Input length / size limit validation
# ---------------------------------------------------------------------------


def validate_string_length(
    value: str,
    field_name: str = "input",
    max_length: int = MAX_STRING_INPUT_LENGTH,
) -> str:
    """Validate that a string does not exceed the maximum length.

    Returns the stripped string.

    Raises
    ------
    ValidationError
        If the string exceeds the length limit.
    """
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string")
    value = value.strip()
    if len(value) > max_length:
        raise ValidationError(
            f"{field_name} too long ({len(value)} chars, max {max_length})"
        )
    return value


def validate_address(address: str) -> str:
    """Validate and return a cleaned address string.

    Raises
    ------
    ValidationError
        If the address is empty or too long.
    """
    address = validate_string_length(address, "address", MAX_ADDRESS_LENGTH)
    if not address:
        raise ValidationError("Address must not be empty")
    return address


def validate_array_length(
    items: list[Any],
    field_name: str = "array",
    max_items: int = MAX_ARRAY_ITEMS,
) -> list[Any]:
    """Validate that an array does not exceed the maximum number of items.

    Raises
    ------
    ValidationError
        If the array has too many items.
    """
    if not isinstance(items, (list, tuple)):
        raise ValidationError(f"{field_name} must be a list")
    if len(items) > max_items:
        raise ValidationError(
            f"{field_name} has too many items ({len(items)}, max {max_items})"
        )
    return list(items)
