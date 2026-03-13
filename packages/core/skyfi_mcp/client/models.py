"""
Re-export all Pydantic models from interfaces.py.

Agent B and other consumers should import models from here:
    from skyfi_mcp.client.models import SearchArchiveInput, SearchArchiveOutput, ...

This module also defines internal-only models used by the API clients.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Internal-only models (used by API clients, not exposed as tool I/O)
# ---------------------------------------------------------------------------
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Re-export everything from interfaces
# ---------------------------------------------------------------------------
from interfaces import (
    AnalyzeFeasibilityInput,
    ArchiveDetailsOutput,
    ArchiveResult,
    AreaBoundaryOutput,
    CheckNotificationsOutput,
    ComparePricingInput,
    ComparePricingOutput,
    DateRange,
    DeleteMonitorInput,
    DeleteMonitorOutput,
    DeliveryFormat,
    DeliveryOptions,
    EstimateArchivePriceInput,
    EstimateArchivePriceOutput,
    ExploreProvidersInput,
    ExploreProvidersOutput,
    FeasibilityAnalysis,
    GeocodeInput,
    GeocodeOutput,
    GeocodeResult,
    GeoJSONGeometry,
    GetArchiveDetailsInput,
    GetAreaBoundaryInput,
    GetOrderImagesInput,
    GetOrderStatusInput,
    GetTaskingQuoteInput,
    GetWebhookStatusInput,
    ListMonitorsOutput,
    ListOrdersInput,
    ListOrdersOutput,
    LocationInput,
    MonitorInfo,
    Notification,
    OrderConfirmation,
    OrderConfirmationPreview,
    OrderImagesOutput,
    OrderStatus,
    OrderStatusOutput,
    PaginationInfo,
    PlaceArchiveOrderInput,
    PlaceOrderOutput,
    PlaceTaskingOrderInput,
    POICategory,
    POIResult,
    PriceBreakdown,
    PricingComparison,
    ProviderInfo,
    ResolutionUnit,
    ReverseGeocodeInput,
    ReverseGeocodeOutput,
    SearchArchiveInput,
    SearchArchiveOutput,
    SearchPOIsInput,
    SearchPOIsOutput,
    SensorType,
    SetupAOIMonitoringInput,
    SetupMonitorOutput,
    TaskingQuoteOutput,
    WebhookStatusOutput,
)


class SkyFiAPIError(BaseModel):
    """Structured error returned by the SkyFi API."""

    status_code: int = Field(..., description="HTTP status code.")
    error: str = Field(..., description="Error type or code.")
    message: str = Field(..., description="Human-readable error message.")
    details: dict[str, Any] = Field(default_factory=dict, description="Extra error details.")


class SkyFiSearchResponse(BaseModel):
    """Raw response shape from POST /archives."""

    archives: list[dict[str, Any]] = Field(default_factory=list)
    next_page: str | None = Field(
        None, alias="nextPage", description="Pagination URL from SkyFi.",
    )
    total: int | None = Field(
        None, description="Total matching results if provided.",
    )


class OSMNominatimResult(BaseModel):
    """Single result from Nominatim search/reverse endpoint."""

    place_id: int | None = None
    licence: str | None = None
    osm_type: str | None = None
    osm_id: int | None = None
    lat: str = ""
    lon: str = ""
    display_name: str = ""
    boundingbox: list[str] = Field(default_factory=list)
    importance: float | None = None
    geojson: dict[str, Any] | None = None


class OverpassElement(BaseModel):
    """Single element from an Overpass API response."""

    type: str = ""
    id: int = 0
    lat: float | None = None
    lon: float | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    center: dict[str, float] | None = None
    geometry: list[dict[str, float]] | None = None


__all__ = [
    # Enums
    "SensorType",
    "OrderStatus",
    "ResolutionUnit",
    "DeliveryFormat",
    "POICategory",
    # Shared models
    "GeoJSONGeometry",
    "LocationInput",
    "DateRange",
    "DeliveryOptions",
    "PriceBreakdown",
    "PaginationInfo",
    # Search inputs/outputs
    "SearchArchiveInput",
    "GetArchiveDetailsInput",
    "ExploreProvidersInput",
    "ArchiveResult",
    "SearchArchiveOutput",
    "ArchiveDetailsOutput",
    "ProviderInfo",
    "ExploreProvidersOutput",
    # Pricing inputs/outputs
    "EstimateArchivePriceInput",
    "GetTaskingQuoteInput",
    "AnalyzeFeasibilityInput",
    "ComparePricingInput",
    "EstimateArchivePriceOutput",
    "TaskingQuoteOutput",
    "FeasibilityAnalysis",
    "PricingComparison",
    "ComparePricingOutput",
    # Order inputs/outputs
    "PlaceArchiveOrderInput",
    "PlaceTaskingOrderInput",
    "GetOrderStatusInput",
    "ListOrdersInput",
    "GetOrderImagesInput",
    "OrderConfirmationPreview",
    "OrderConfirmation",
    "PlaceOrderOutput",
    "OrderStatusOutput",
    "ListOrdersOutput",
    "OrderImagesOutput",
    # Monitoring inputs/outputs
    "SetupAOIMonitoringInput",
    "DeleteMonitorInput",
    "GetWebhookStatusInput",
    "MonitorInfo",
    "SetupMonitorOutput",
    "ListMonitorsOutput",
    "DeleteMonitorOutput",
    "WebhookStatusOutput",
    "Notification",
    "CheckNotificationsOutput",
    # Geo inputs/outputs
    "GeocodeInput",
    "ReverseGeocodeInput",
    "SearchPOIsInput",
    "GetAreaBoundaryInput",
    "GeocodeResult",
    "GeocodeOutput",
    "ReverseGeocodeOutput",
    "POIResult",
    "SearchPOIsOutput",
    "AreaBoundaryOutput",
    # Internal models
    "SkyFiAPIError",
    "SkyFiSearchResponse",
    "OSMNominatimResult",
    "OverpassElement",
]
