"""
Geospatial utility tools — OpenStreetMap integration.

Provides geocoding, reverse geocoding, POI search, and area boundary
lookup via the Nominatim and Overpass APIs.
"""

from __future__ import annotations

from interfaces import (
    AreaBoundaryOutput,
    GeocodeInput,
    GeocodeOutput,
    GetAreaBoundaryInput,
    ReverseGeocodeInput,
    ReverseGeocodeOutput,
    SearchPOIsInput,
    SearchPOIsOutput,
)

from skyfi_mcp.client.osm import OSMClient
from skyfi_mcp.validation import (
    validate_address,
    validate_geojson_geometry,
    validate_string_length,
    MAX_AREA_NAME_LENGTH,
)


def _validate_location(location: object) -> None:
    """Validate a LocationInput's geometry and address fields."""
    geometry = getattr(location, "geometry", None)
    address = getattr(location, "address", None)
    if geometry is not None:
        validate_geojson_geometry(geometry)
    if address is not None:
        validate_address(address)


async def geocode(
    client: OSMClient,
    input: GeocodeInput,
) -> GeocodeOutput:
    """Convert an address or place name to coordinates."""
    validate_string_length(input.query, "query")
    return await client.geocode(input.query)


async def reverse_geocode(
    client: OSMClient,
    input: ReverseGeocodeInput,
) -> ReverseGeocodeOutput:
    """Convert coordinates to an address."""
    return await client.reverse_geocode(input.lat, input.lon)


async def search_pois(
    client: OSMClient,
    input: SearchPOIsInput,
) -> SearchPOIsOutput:
    """Find points of interest near a location."""
    _validate_location(input.location)

    # Resolve location to lat/lon
    if input.location.geometry is not None:
        coords = input.location.geometry.coordinates
        if input.location.geometry.type == "Point":
            lat, lon = coords[1], coords[0]
        else:
            # For polygons, use centroid approximation (first coord)
            flat = coords[0] if isinstance(coords[0][0], list) else coords
            lats = [p[1] for p in flat]
            lons = [p[0] for p in flat]
            lat = sum(lats) / len(lats)
            lon = sum(lons) / len(lons)
    elif input.location.address is not None:
        # Geocode the address first
        geo_result = await client.geocode(input.location.address)
        if not geo_result.results:
            return SearchPOIsOutput(results=[])
        lat = geo_result.results[0].lat
        lon = geo_result.results[0].lon
    else:
        raise ValueError("A location (geometry or address) is required for POI search.")

    return await client.search_pois(
        lat=lat,
        lon=lon,
        radius=input.radius,
        category=input.category,
    )


async def get_area_boundary(
    client: OSMClient,
    input: GetAreaBoundaryInput,
) -> AreaBoundaryOutput:
    """Get the GeoJSON boundary polygon for a named area."""
    # Validate name length (sanitization happens inside OSMClient)
    validate_string_length(input.name, "name", MAX_AREA_NAME_LENGTH)
    return await client.get_area_boundary(
        name=input.name,
        admin_level=input.admin_level,
    )
