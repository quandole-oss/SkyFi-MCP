"""
Pricing & Feasibility tools.

Provides archive price estimation, tasking quotes, feasibility analysis,
and cross-provider pricing comparison.
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

if TYPE_CHECKING:
    from skyfi_mcp.client.skyfi import SkyFiClient

logger = logging.getLogger(__name__)


def _location_dict(loc: Any) -> dict[str, Any]:
    """Convert a LocationInput to a plain dict for the API client."""
    payload: dict[str, Any] = {}
    if loc.geometry is not None:
        payload["geometry"] = loc.geometry.model_dump()
    if loc.address is not None:
        payload["address"] = loc.address
    return payload


def _parse_price(raw: dict[str, Any]) -> PriceBreakdown:
    """Parse a price breakdown from raw API data."""
    return PriceBreakdown(
        subtotal=float(raw.get("subtotal", 0)),
        processing_fee=float(raw.get("processingFee", raw.get("processing_fee", 0))),
        total=float(raw.get("total", 0)),
        currency=raw.get("currency", "USD"),
    )


async def estimate_archive_price(
    client: SkyFiClient,
    input: EstimateArchivePriceInput,
    api_key: str,
) -> EstimateArchivePriceOutput:
    """Get a price estimate for an archive image."""
    delivery_opts: dict[str, Any] | None = None
    if input.delivery_options is not None:
        delivery_opts = input.delivery_options.model_dump()

    raw = await client.estimate_archive_price(
        api_key,
        archive_id=input.archive_id,
        delivery_options=delivery_opts,
    )

    price = _parse_price(raw.get("price", raw))
    delivery = input.delivery_options or DeliveryOptions()

    return EstimateArchivePriceOutput(
        archive_id=input.archive_id,
        price=price,
        delivery_options=delivery,
        estimated_delivery_time=raw.get("estimatedDeliveryTime"),
    )


async def get_tasking_quote(
    client: SkyFiClient,
    input: GetTaskingQuoteInput,
    api_key: str,
) -> TaskingQuoteOutput:
    """Obtain a tasking quote for new imagery capture."""
    location = _location_dict(input.location)
    time_window: dict[str, Any] | None = None
    if input.time_window is not None:
        time_window = {
            "start": input.time_window.start.isoformat(),
            "end": input.time_window.end.isoformat(),
        }

    raw = await client.get_tasking_quote(
        api_key,
        location=location,
        resolution=input.resolution,
        sensor_type=input.sensor_type.value if input.sensor_type else None,
        time_window=time_window,
    )

    price = _parse_price(raw.get("price", {}))

    estimated_window: DateRange | None = None
    if raw.get("estimatedCaptureWindow"):
        w = raw["estimatedCaptureWindow"]
        estimated_window = DateRange(start=w["start"], end=w["end"])

    return TaskingQuoteOutput(
        quote_id=raw["quoteId"],
        price=price,
        feasibility_score=float(raw.get("feasibilityScore", 0.5)),
        estimated_capture_window=estimated_window,
        provider=raw.get("provider"),
        resolution=raw.get("resolution"),
        expires_at=raw.get("expiresAt"),
    )


async def analyze_feasibility(
    client: SkyFiClient,
    input: AnalyzeFeasibilityInput,
    api_key: str,
) -> FeasibilityAnalysis:
    """Analyze the feasibility of capturing imagery over an AOI."""
    location = _location_dict(input.location)
    time_window: dict[str, Any] | None = None
    if input.time_window is not None:
        time_window = {
            "start": input.time_window.start.isoformat(),
            "end": input.time_window.end.isoformat(),
        }

    raw = await client.analyze_feasibility(
        api_key,
        location=location,
        time_window=time_window,
        resolution=input.resolution,
    )

    capture_windows: list[DateRange] = []
    for w in raw.get("captureWindows", []):
        capture_windows.append(DateRange(start=w["start"], end=w["end"]))

    return FeasibilityAnalysis(
        feasibility_score=float(raw.get("feasibilityScore", 0)),
        cloud_forecast=raw.get("cloudForecast"),
        satellite_passes=raw.get("satellitePasses", []),
        capture_windows=capture_windows,
        recommendations=raw.get("recommendations"),
    )


async def compare_pricing(
    client: SkyFiClient,
    input: ComparePricingInput,
    api_key: str,
) -> ComparePricingOutput:
    """Compare pricing across providers and resolution tiers."""
    location = _location_dict(input.location)
    raw = await client.compare_pricing(
        api_key,
        location=location,
        resolution_options=input.resolution_options,
    )

    comparisons: list[PricingComparison] = []
    for item in raw.get("comparisons", []):
        comparisons.append(
            PricingComparison(
                provider=item["provider"],
                resolution=float(item["resolution"]),
                price=_parse_price(item.get("price", {})),
                sensor_type=SensorType(item.get("sensorType", "optical")),
            )
        )

    recommended: PricingComparison | None = None
    rec = raw.get("recommended")
    if rec:
        recommended = PricingComparison(
            provider=rec["provider"],
            resolution=float(rec["resolution"]),
            price=_parse_price(rec.get("price", {})),
            sensor_type=SensorType(rec.get("sensorType", "optical")),
        )

    return ComparePricingOutput(comparisons=comparisons, recommended=recommended)
