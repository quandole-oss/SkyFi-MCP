"""
OpenStreetMap client — Nominatim geocoding and Overpass API queries.

Respects Nominatim's usage policy (1 request per second, descriptive User-Agent).
"""

from __future__ import annotations

import asyncio
import logging
import time
from math import atan2, cos, radians, sin, sqrt
from typing import Any

import httpx

from skyfi_mcp.client.models import (
    AreaBoundaryOutput,
    GeoJSONGeometry,
    GeocodeOutput,
    GeocodeResult,
    POICategory,
    POIResult,
    ReverseGeocodeOutput,
    SearchPOIsOutput,
)
from skyfi_mcp.validation import sanitize_overpass_value

logger = logging.getLogger(__name__)

_NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
_OVERPASS_BASE = "https://overpass-api.de/api/interpreter"
_USER_AGENT = "SkyFi-MCP/1.0"
_DEFAULT_TIMEOUT = 30.0


# Map POICategory enum values to Overpass tag filters
_POI_OVERPASS_TAGS: dict[str, str] = {
    "airport": '["aeroway"="aerodrome"]',
    "port": '["landuse"="port"]',
    "military": '["landuse"="military"]',
    "industrial": '["landuse"="industrial"]',
    "commercial": '["landuse"="commercial"]',
    "residential": '["landuse"="residential"]',
    "natural": '["natural"]',
    "water": '["natural"="water"]',
    "transportation": '["highway"]',
}


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in meters between two lat/lon points."""
    r = 6_371_000  # Earth radius in meters
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return r * 2 * atan2(sqrt(a), sqrt(1 - a))


class OSMClient:
    """Async client for OpenStreetMap Nominatim and Overpass APIs.

    Parameters
    ----------
    nominatim_url:
        Base URL for Nominatim. Defaults to the public instance.
    overpass_url:
        Full URL for the Overpass interpreter endpoint.
    timeout:
        HTTP timeout in seconds.
    """

    def __init__(
        self,
        nominatim_url: str = _NOMINATIM_BASE,
        overpass_url: str = _OVERPASS_BASE,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._nominatim_url = nominatim_url.rstrip("/")
        self._overpass_url = overpass_url
        self._timeout = timeout
        # Track last Nominatim request time for rate-limiting (1 req/sec)
        self._last_nominatim_request: float = 0.0

    def _common_headers(self) -> dict[str, str]:
        return {"User-Agent": _USER_AGENT}

    async def _nominatim_throttle(self) -> None:
        """Ensure at least 1 second between Nominatim requests."""
        now = time.monotonic()
        elapsed = now - self._last_nominatim_request
        if elapsed < 1.0:
            await asyncio.sleep(1.0 - elapsed)
        self._last_nominatim_request = time.monotonic()

    # --------------------------------------------------------------------- #
    # Geocoding
    # --------------------------------------------------------------------- #

    async def geocode(self, query: str) -> GeocodeOutput:
        """Forward geocode a text query to coordinates.

        Uses Nominatim /search endpoint.
        """
        await self._nominatim_throttle()
        params: dict[str, Any] = {
            "q": query,
            "format": "jsonv2",
            "limit": 5,
            "polygon_geojson": 1,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._nominatim_url}/search",
                params=params,
                headers=self._common_headers(),
            )
            resp.raise_for_status()
            data: list[dict[str, Any]] = resp.json()

        results: list[GeocodeResult] = []
        for item in data:
            geojson = item.get("geojson")
            geometry = (
                GeoJSONGeometry(type=geojson["type"], coordinates=geojson["coordinates"])
                if geojson
                else None
            )
            results.append(
                GeocodeResult(
                    lat=float(item["lat"]),
                    lon=float(item["lon"]),
                    display_name=item.get("display_name", ""),
                    geometry=geometry,
                    osm_type=item.get("osm_type"),
                    osm_id=int(item["osm_id"]) if item.get("osm_id") else None,
                    importance=item.get("importance"),
                )
            )
        return GeocodeOutput(results=results)

    async def reverse_geocode(self, lat: float, lon: float) -> ReverseGeocodeOutput:
        """Reverse geocode coordinates to an address.

        Uses Nominatim /reverse endpoint.
        """
        await self._nominatim_throttle()
        params: dict[str, Any] = {
            "lat": lat,
            "lon": lon,
            "format": "jsonv2",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._nominatim_url}/reverse",
                params=params,
                headers=self._common_headers(),
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()

        return ReverseGeocodeOutput(
            address=data.get("display_name", ""),
            lat=float(data.get("lat", lat)),
            lon=float(data.get("lon", lon)),
            details=data.get("address", {}),
        )

    # --------------------------------------------------------------------- #
    # Overpass — POI search
    # --------------------------------------------------------------------- #

    async def search_pois(
        self,
        lat: float,
        lon: float,
        radius: float = 1000,
        category: POICategory | None = None,
    ) -> SearchPOIsOutput:
        """Search for points of interest near a location using Overpass API."""
        tag_filter = _POI_OVERPASS_TAGS.get(category.value, "") if category else ""

        # Build a simple Overpass QL around query
        query = f"""
[out:json][timeout:25];
(
  node{tag_filter}(around:{radius},{lat},{lon});
  way{tag_filter}(around:{radius},{lat},{lon});
);
out center body;
"""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                self._overpass_url,
                data={"data": query},
                headers=self._common_headers(),
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()

        results: list[POIResult] = []
        for elem in data.get("elements", []):
            tags = elem.get("tags", {})
            name = tags.get("name", "")
            if not name:
                continue  # Skip unnamed features
            elem_lat = elem.get("lat") or (elem.get("center", {}) or {}).get("lat")
            elem_lon = elem.get("lon") or (elem.get("center", {}) or {}).get("lon")
            if elem_lat is None or elem_lon is None:
                continue
            distance = _haversine(lat, lon, float(elem_lat), float(elem_lon))
            cat_str = (
                category.value
                if category
                else tags.get("landuse", tags.get("natural", tags.get("aeroway", "other")))
            )
            results.append(
                POIResult(
                    name=name,
                    category=cat_str,
                    lat=float(elem_lat),
                    lon=float(elem_lon),
                    distance_m=round(distance, 1),
                    osm_id=elem.get("id"),
                    tags=tags,
                )
            )

        # Sort by distance
        results.sort(key=lambda r: r.distance_m or 0)
        return SearchPOIsOutput(results=results)

    # --------------------------------------------------------------------- #
    # Overpass — Area boundaries
    # --------------------------------------------------------------------- #

    async def get_area_boundary(
        self,
        name: str,
        admin_level: int | None = None,
    ) -> AreaBoundaryOutput:
        """Fetch the boundary polygon of a named area (city, region, etc.)."""
        # Sanitize user input to prevent Overpass QL injection
        safe_name = sanitize_overpass_value(name)

        # admin_level is already validated as int|None by the input model,
        # but clamp it to valid OSM range as defense-in-depth
        admin_filter = ""
        if admin_level is not None:
            admin_level = max(1, min(11, int(admin_level)))
            admin_filter = f'["admin_level"="{admin_level}"]'

        query = f"""
[out:json][timeout:25];
relation["name"="{safe_name}"]["boundary"="administrative"]{admin_filter};
out geom;
"""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                self._overpass_url,
                data={"data": query},
                headers=self._common_headers(),
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()

        elements = data.get("elements", [])
        if not elements:
            raise ValueError(f"No boundary found for '{name}'")

        elem = elements[0]
        tags = elem.get("tags", {})

        # Build a polygon from the relation members
        coords = self._extract_boundary_coords(elem)
        geometry = GeoJSONGeometry(type="Polygon", coordinates=[coords])

        return AreaBoundaryOutput(
            name=tags.get("name", name),
            geometry=geometry,
            admin_level=int(tags["admin_level"]) if "admin_level" in tags else admin_level,
            osm_id=elem.get("id"),
        )

    @staticmethod
    def _extract_boundary_coords(element: dict[str, Any]) -> list[list[float]]:
        """Extract coordinate ring from an Overpass relation with geom output."""
        coords: list[list[float]] = []
        for member in element.get("members", []):
            if member.get("type") == "way" and member.get("role") == "outer":
                for pt in member.get("geometry", []):
                    coords.append([pt["lon"], pt["lat"]])
        # Close the ring if not already closed
        if coords and coords[0] != coords[-1]:
            coords.append(coords[0])
        # Fallback: if no members with geometry, try bounds
        if not coords:
            bounds = element.get("bounds", {})
            if bounds:
                s, n = bounds.get("minlat", 0), bounds.get("maxlat", 0)
                w, e = bounds.get("minlon", 0), bounds.get("maxlon", 0)
                coords = [[w, s], [e, s], [e, n], [w, n], [w, s]]
        return coords
