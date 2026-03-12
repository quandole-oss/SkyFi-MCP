"""
Search & Discovery tools.

Provides archive search (with pagination), archive detail retrieval,
and provider exploration.
"""

from __future__ import annotations

import logging
from typing import Any

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

from skyfi_mcp.client.skyfi import SkyFiClient

logger = logging.getLogger(__name__)


def _location_payload(input_model: SearchArchiveInput | ExploreProvidersInput) -> dict[str, Any] | None:
    """Convert a LocationInput to the dict expected by the SkyFi client."""
    loc = getattr(input_model, "location", None)
    if loc is None:
        return None
    payload: dict[str, Any] = {}
    if loc.geometry is not None:
        payload["geometry"] = loc.geometry.model_dump()
    if loc.address is not None:
        payload["address"] = loc.address
    return payload or None


async def search_archive(
    client: SkyFiClient,
    input: SearchArchiveInput,
    api_key: str,
) -> SearchArchiveOutput:
    """Search the SkyFi archive catalogue with pagination support.

    Handles the ``nextPage`` cursor returned by the API and translates it
    into the ``PaginationInfo`` model.
    """
    location = _location_payload(input)
    if location is None:
        raise ValueError("A location (geometry or address) is required for archive search.")

    date_range: dict[str, Any] | None = None
    if input.date_range is not None:
        date_range = {
            "start": input.date_range.start.isoformat(),
            "end": input.date_range.end.isoformat(),
        }

    raw = await client.search_archive(
        api_key,
        location=location,
        date_range=date_range,
        resolution_min=input.resolution_min,
        sensor_type=input.sensor_type.value if input.sensor_type else None,
        cloud_cover_max=input.cloud_cover_max,
        open_data=input.open_data,
        page_token=input.page_token,
    )

    # Parse results
    results: list[ArchiveResult] = []
    for item in raw.get("results", []):
        results.append(
            ArchiveResult(
                archive_id=item["archiveId"],
                provider=item.get("provider", "unknown"),
                sensor_type=SensorType(item.get("sensorType", "optical")),
                resolution=float(item.get("resolution", 0)),
                capture_date=item["captureDate"],
                cloud_cover=item.get("cloudCover"),
                geometry=GeoJSONGeometry(**item["geometry"]),
                thumbnail_url=item.get("thumbnailUrl"),
                open_data=item.get("openData", False),
            )
        )

    # Build pagination info
    next_page = raw.get("nextPage")
    total_count = raw.get("totalCount")
    pagination = PaginationInfo(
        has_more=next_page is not None,
        next_offset=next_page,
        total_count=total_count,
    )

    return SearchArchiveOutput(results=results, pagination=pagination)


async def get_archive_details(
    client: SkyFiClient,
    input: GetArchiveDetailsInput,
    api_key: str,
) -> ArchiveDetailsOutput:
    """Retrieve full metadata for a single archive image."""
    raw = await client.get_archive_details(api_key, archive_id=input.archive_id)
    return ArchiveDetailsOutput(
        archive_id=raw["archiveId"],
        provider=raw.get("provider", "unknown"),
        sensor_type=SensorType(raw.get("sensorType", "optical")),
        resolution=float(raw.get("resolution", 0)),
        capture_date=raw["captureDate"],
        cloud_cover=raw.get("cloudCover"),
        geometry=GeoJSONGeometry(**raw["geometry"]),
        bands=raw.get("bands", []),
        file_size_mb=raw.get("fileSizeMb"),
        license=raw.get("license"),
        metadata=raw.get("metadata", {}),
    )


async def explore_providers(
    client: SkyFiClient,
    input: ExploreProvidersInput,
    api_key: str,
) -> ExploreProvidersOutput:
    """List available imagery providers, optionally filtered by location/sensor."""
    location = _location_payload(input)
    raw = await client.get_providers(
        api_key,
        location=location,
        sensor_type=input.sensor_type.value if input.sensor_type else None,
    )

    providers: list[ProviderInfo] = []
    for item in raw.get("providers", []):
        sensor_types = [SensorType(s) for s in item.get("sensorTypes", ["optical"])]
        res_range = item.get("resolutionRange", [0.3, 30.0])
        providers.append(
            ProviderInfo(
                provider_id=item["providerId"],
                name=item.get("name", item["providerId"]),
                sensor_types=sensor_types,
                resolution_range=(float(res_range[0]), float(res_range[1])),
                coverage_description=item.get("coverageDescription"),
            )
        )

    return ExploreProvidersOutput(providers=providers)
