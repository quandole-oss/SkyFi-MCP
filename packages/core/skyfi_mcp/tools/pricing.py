"""
Pricing & Feasibility tools.

Provides archive price estimation, tasking pricing, feasibility analysis,
and cross-provider pricing comparison.

Maps between MCP tool inputs and the real SkyFi Platform API endpoints:
- POST /pricing          (tasking pricing options)
- POST /feasibility      (feasibility check)
- GET  /archives/{id}    (archive pricing is embedded in archive data)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from interfaces import (
    AnalyzeFeasibilityInput,
    ComparePricingInput,
    ComparePricingOutput,
    DateRange,
    DeliveryOptions,
    EstimateArchivePriceInput,
    EstimateArchivePriceOutput,
    FeasibilityAnalysis,
    GetTaskingQuoteInput,
    PriceBreakdown,
    PricingComparison,
    SensorType,
    TaskingQuoteOutput,
)
from skyfi_mcp.client.wkt import geojson_to_wkt

if TYPE_CHECKING:
    from skyfi_mcp.client.skyfi import SkyFiClient

logger = logging.getLogger(__name__)


def _location_to_wkt(loc: Any) -> str:
    """Convert a LocationInput to a WKT string."""
    if loc.geometry is not None:
        return geojson_to_wkt(loc.geometry.model_dump())
    raise ValueError("A geometry is required (address-only not supported for this endpoint).")


def _parse_price(raw: dict[str, Any]) -> PriceBreakdown:
    """Parse a price breakdown from raw API data."""
    return PriceBreakdown(
        subtotal=float(raw.get("subtotal", raw.get("priceForOneSquareKm", 0))),
        processing_fee=float(raw.get("processingFee", raw.get("processing_fee", 0))),
        total=float(raw.get("total", raw.get("priceFullScene", 0))),
        currency=raw.get("currency", "USD"),
    )


async def estimate_archive_price(
    client: SkyFiClient,
    input: EstimateArchivePriceInput,
    api_key: str,
) -> EstimateArchivePriceOutput:
    """Get a price estimate for an archive image.

    The SkyFi API embeds pricing in archive details, so we fetch the
    archive metadata and extract the price fields.
    """
    raw = await client.get_archive(api_key, archive_id=input.archive_id)

    price = PriceBreakdown(
        subtotal=float(raw.get("priceForOneSquareKm", 0)),
        processing_fee=0.0,
        total=float(raw.get("priceFullScene", 0)),
        currency="USD",
    )
    delivery = input.delivery_options or DeliveryOptions()

    return EstimateArchivePriceOutput(
        archive_id=input.archive_id,
        price=price,
        delivery_options=delivery,
        estimated_delivery_time=f"{raw.get('deliveryTimeHours', 24)} hours",
    )


async def get_tasking_quote(
    client: SkyFiClient,
    input: GetTaskingQuoteInput,
    api_key: str,
) -> TaskingQuoteOutput:
    """Get tasking pricing options.

    Uses POST /pricing with an optional AOI.
    """
    aoi = _location_to_wkt(input.location)
    body: dict[str, Any] = {"aoi": aoi}

    raw = await client.get_pricing(api_key, body=body)

    # POST /pricing returns pricing options; build a quote-like response
    price = _parse_price(raw)

    estimated_window: DateRange | None = None
    if input.time_window:
        estimated_window = input.time_window

    return TaskingQuoteOutput(
        quote_id=raw.get("quoteId", "pricing-estimate"),
        price=price,
        feasibility_score=float(raw.get("feasibilityScore", 0.5)),
        estimated_capture_window=estimated_window,
        provider=raw.get("provider"),
        resolution=None,  # API returns resolution as string tier, not float
        expires_at=raw.get("expiresAt"),
    )


async def analyze_feasibility(
    client: SkyFiClient,
    input: AnalyzeFeasibilityInput,
    api_key: str,
) -> FeasibilityAnalysis:
    """Analyze the feasibility of capturing imagery over an AOI.

    Uses POST /feasibility which requires aoi, productType, resolution,
    startDate, and endDate.
    """
    aoi = _location_to_wkt(input.location)

    body: dict[str, Any] = {"aoi": aoi}

    # Map sensor_type-like resolution to the API's product type and resolution
    # Default to DAY/HIGH if not specified
    body["productType"] = "DAY"
    body["resolution"] = "HIGH"

    if input.time_window is not None:
        body["startDate"] = input.time_window.start.isoformat()
        body["endDate"] = input.time_window.end.isoformat()
    else:
        # API requires dates; use a 7-day window from now
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        body["startDate"] = now.isoformat()
        body["endDate"] = (now + timedelta(days=7)).isoformat()

    raw = await client.create_feasibility(api_key, body=body)

    capture_windows: list[DateRange] = []
    for w in raw.get("captureWindows", raw.get("windows", [])):
        if isinstance(w, dict) and "start" in w:
            capture_windows.append(DateRange(start=w["start"], end=w["end"]))

    return FeasibilityAnalysis(
        feasibility_score=float(raw.get("feasibilityScore", raw.get("score", 0))),
        cloud_forecast=raw.get("cloudForecast"),
        satellite_passes=raw.get("satellitePasses", raw.get("passes", [])),
        capture_windows=capture_windows,
        recommendations=raw.get("recommendations", raw.get("message")),
    )


async def compare_pricing(
    client: SkyFiClient,
    input: ComparePricingInput,
    api_key: str,
) -> ComparePricingOutput:
    """Compare pricing across providers and resolution tiers.

    Uses POST /pricing with an AOI.
    """
    aoi = _location_to_wkt(input.location)
    body: dict[str, Any] = {"aoi": aoi}

    raw = await client.get_pricing(api_key, body=body)

    comparisons: list[PricingComparison] = []
    for item in raw.get("comparisons", raw.get("options", [])):
        comparisons.append(
            PricingComparison(
                provider=item.get("provider", "SkyFi"),
                resolution=float(item.get("gsd", item.get("resolution", 0))),
                price=_parse_price(item.get("price", item)),
                sensor_type=SensorType("optical"),
            )
        )

    # If no comparisons from the API, build a summary from the raw pricing
    if not comparisons and raw:
        comparisons.append(
            PricingComparison(
                provider="SkyFi",
                resolution=0.0,
                price=_parse_price(raw),
                sensor_type=SensorType("optical"),
            )
        )

    recommended = comparisons[0] if comparisons else None

    return ComparePricingOutput(comparisons=comparisons, recommended=recommended)
