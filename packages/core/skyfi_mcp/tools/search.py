"""
Search & Discovery tools.

Provides archive search (with pagination), archive detail retrieval,
and provider exploration.

Bridges between MCP tool inputs (GeoJSON, friendly param names) and the
real SkyFi Platform API (WKT geometries, API-specific field names).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

from interfaces import (
    ArchiveDetailsOutput,
    ArchiveResult,
    ExploreProvidersInput,
    ExploreProvidersOutput,
    GeoJSONGeometry,
    GetArchiveDetailsInput,
    PaginationInfo,
    ProviderInfo,
    SearchArchiveInput,
    SearchArchiveOutput,
    SensorType,
)
from skyfi_mcp.client.wkt import geojson_to_wkt, wkt_to_geojson

if TYPE_CHECKING:
    from skyfi_mcp.client.skyfi import SkyFiClient

logger = logging.getLogger(__name__)

# ---- SensorType <-> productType mapping ------------------------------------

_SENSOR_TO_PRODUCT: dict[str, list[str]] = {
    "optical": ["DAY"],
    "sar": ["SAR"],
    "multispectral": ["MULTISPECTRAL"],
    "hyperspectral": ["HYPERSPECTRAL"],
}

_PRODUCT_TO_SENSOR: dict[str, str] = {
    "DAY": "optical",
    "NIGHT": "optical",
    "VIDEO": "optical",
    "SAR": "sar",
    "MULTISPECTRAL": "multispectral",
    "HYPERSPECTRAL": "hyperspectral",
    "STEREO": "optical",
    "BASEMAP": "optical",
}

# Known SkyFi providers (from the OpenAPI spec ApiProvider enum)
_PROVIDERS: list[dict[str, Any]] = [
    {"id": "PLANET", "name": "Planet Labs", "sensors": ["optical", "multispectral"]},
    {"id": "SATELLOGIC", "name": "Satellogic", "sensors": ["optical", "multispectral"]},
    {"id": "UMBRA", "name": "Umbra", "sensors": ["sar"]},
    {"id": "SIWEI", "name": "SiWei", "sensors": ["optical"]},
    {"id": "GEOSAT", "name": "GeoSat", "sensors": ["optical"]},
    {"id": "ICEYE_US", "name": "ICEYE", "sensors": ["sar"]},
    {"id": "IMPRO", "name": "ImPro", "sensors": ["optical"]},
    {"id": "URBAN_SKY", "name": "Urban Sky", "sensors": ["optical"]},
    {"id": "NSL", "name": "NSL", "sensors": ["optical"]},
    {"id": "VEXCEL", "name": "Vexcel", "sensors": ["optical"]},
    {"id": "VANTOR", "name": "Vantor", "sensors": ["optical"]},
    {"id": "SENTINEL1_CREODIAS", "name": "Sentinel-1 (Creodias)", "sensors": ["sar"]},
    {"id": "SENTINEL2", "name": "Sentinel-2", "sensors": ["multispectral"]},
    {"id": "SENTINEL2_CREODIAS", "name": "Sentinel-2 (Creodias)", "sensors": ["multispectral"]},
]


def _location_to_wkt(input_model: SearchArchiveInput | ExploreProvidersInput) -> str | None:
    """Convert a LocationInput to a WKT string for the SkyFi API."""
    loc = getattr(input_model, "location", None)
    if loc is None:
        return None
    if loc.geometry is not None:
        return geojson_to_wkt(loc.geometry.model_dump())
    return None


def _parse_archive(item: dict[str, Any]) -> ArchiveResult:
    """Parse a single archive result from the real API response."""
    product_type = item.get("productType", "DAY")
    sensor_str = _PRODUCT_TO_SENSOR.get(product_type, "optical")
    gsd = item.get("gsd", item.get("platformResolution", 0))

    # Parse footprint from WKT to GeoJSON
    footprint_wkt = item.get("footprint", "")
    if footprint_wkt:
        geom = GeoJSONGeometry(**wkt_to_geojson(footprint_wkt))
    else:
        geom = GeoJSONGeometry(type="Polygon", coordinates=[])

    # Get the first available thumbnail URL
    thumb_urls = item.get("thumbnailUrls", {})
    thumbnail_url = next(iter(thumb_urls.values()), None) if thumb_urls else None

    return ArchiveResult(
        archive_id=item["archiveId"],
        provider=item.get("provider", "unknown"),
        sensor_type=SensorType(sensor_str),
        resolution=float(gsd),
        capture_date=item.get("captureTimestamp", item.get("captureDate", "")),
        cloud_cover=item.get("cloudCoveragePercent"),
        geometry=geom,
        thumbnail_url=thumbnail_url,
        open_data=item.get("openData", False),
    )


async def search_archive(
    client: SkyFiClient,
    input: SearchArchiveInput,
    api_key: str,
) -> SearchArchiveOutput:
    """Search the SkyFi archive catalogue with pagination support."""
    # Handle pagination: if page_token is set, use GET with the page param
    if input.page_token:
        # page_token may be a full URL path like /platform-api/archives?page=...
        # or just the raw page token. Extract the token if it's a URL.
        token = input.page_token
        parsed = urlparse(token)
        if parsed.query:
            token = parse_qs(parsed.query).get("page", [token])[0]
        raw = await client.search_archives_page(api_key, page_token=token)
    else:
        # Build the search body for POST /archives
        aoi = _location_to_wkt(input)
        if aoi is None:
            raise ValueError("A location (geometry or address) is required for archive search.")

        body: dict[str, Any] = {"aoi": aoi}

        if input.date_range is not None:
            body["fromDate"] = input.date_range.start.isoformat()
            body["toDate"] = input.date_range.end.isoformat()
        if input.cloud_cover_max is not None:
            body["maxCloudCoveragePercent"] = input.cloud_cover_max
        if input.sensor_type is not None:
            product_types = _SENSOR_TO_PRODUCT.get(input.sensor_type.value)
            if product_types:
                body["productTypes"] = product_types
        if input.open_data is not None:
            body["openData"] = input.open_data

        raw = await client.search_archives(api_key, body=body)

    # Parse results -- real API returns "archives" not "results"
    results: list[ArchiveResult] = []
    for item in raw.get("archives", []):
        results.append(_parse_archive(item))

    # Build pagination info
    next_page = raw.get("nextPage")
    pagination = PaginationInfo(
        has_more=next_page is not None,
        next_offset=next_page,
        total_count=raw.get("total"),
    )

    return SearchArchiveOutput(results=results, pagination=pagination)


async def get_archive_details(
    client: SkyFiClient,
    input: GetArchiveDetailsInput,
    api_key: str,
) -> ArchiveDetailsOutput:
    """Retrieve full metadata for a single archive image."""
    raw = await client.get_archive(api_key, archive_id=input.archive_id)

    product_type = raw.get("productType", "DAY")
    sensor_str = _PRODUCT_TO_SENSOR.get(product_type, "optical")
    gsd = raw.get("gsd", raw.get("platformResolution", 0))

    footprint_wkt = raw.get("footprint", "")
    geom = GeoJSONGeometry(**wkt_to_geojson(footprint_wkt)) if footprint_wkt else GeoJSONGeometry(
        type="Polygon", coordinates=[]
    )

    return ArchiveDetailsOutput(
        archive_id=raw["archiveId"],
        provider=raw.get("provider", "unknown"),
        sensor_type=SensorType(sensor_str),
        resolution=float(gsd),
        capture_date=raw.get("captureTimestamp", raw.get("captureDate", "")),
        cloud_cover=raw.get("cloudCoveragePercent"),
        geometry=geom,
        bands=raw.get("bands", []),
        file_size_mb=raw.get("fileSizeMb"),
        license=raw.get("license"),
        metadata={
            k: raw[k]
            for k in (
                "constellation", "resolution", "totalAreaSquareKm",
                "priceForOneSquareKm", "priceFullScene", "deliveryTimeHours",
                "overlapRatio", "overlapSqkm", "minSqKm", "maxSqKm",
            )
            if k in raw
        },
    )


async def explore_providers(
    client: SkyFiClient,
    input: ExploreProvidersInput,
    api_key: str,
) -> ExploreProvidersOutput:
    """List available imagery providers.

    The SkyFi API doesn't have a dedicated providers endpoint, so this
    returns the known provider list from the API specification.
    """
    providers: list[ProviderInfo] = []
    filter_sensor = input.sensor_type.value if input.sensor_type else None

    for p in _PROVIDERS:
        if filter_sensor and filter_sensor not in p["sensors"]:
            continue
        sensor_types = [SensorType(s) for s in p["sensors"]]
        providers.append(
            ProviderInfo(
                provider_id=p["id"],
                name=p["name"],
                sensor_types=sensor_types,
                resolution_range=(0.3, 30.0),
                coverage_description=None,
            )
        )

    return ExploreProvidersOutput(providers=providers)
