"""
SkyFi MCP Server — Shared Interfaces & Data Contracts

This module defines the Protocol types and Pydantic models that all agents
(A, B, C) depend on. It is the single source of truth for tool signatures,
input/output schemas, and service contracts.

Orchestrator owns this file. Agents MUST NOT modify it without orchestrator approval.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SensorType(str, Enum):
    """Satellite sensor types supported by SkyFi."""

    OPTICAL = "optical"
    SAR = "sar"
    MULTISPECTRAL = "multispectral"
    HYPERSPECTRAL = "hyperspectral"


class OrderStatus(str, Enum):
    """Possible states of a SkyFi order."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ResolutionUnit(str, Enum):
    """Resolution measurement units."""

    CM = "cm"
    M = "m"


class DeliveryFormat(str, Enum):
    """Supported imagery delivery formats."""

    GEOTIFF = "geotiff"
    JPEG2000 = "jpeg2000"
    PNG = "png"
    COG = "cog"  # Cloud-Optimized GeoTIFF


class POICategory(str, Enum):
    """OpenStreetMap point-of-interest categories."""

    AIRPORT = "airport"
    PORT = "port"
    MILITARY = "military"
    INDUSTRIAL = "industrial"
    COMMERCIAL = "commercial"
    RESIDENTIAL = "residential"
    NATURAL = "natural"
    WATER = "water"
    TRANSPORTATION = "transportation"


# ---------------------------------------------------------------------------
# Shared Data Models
# ---------------------------------------------------------------------------


class GeoJSONGeometry(BaseModel):
    """GeoJSON geometry object (Point, Polygon, MultiPolygon)."""

    type: str = Field(
        ...,
        description="GeoJSON geometry type: Point, Polygon, MultiPolygon, etc.",
    )
    coordinates: Any = Field(
        ...,
        description="Coordinate array per GeoJSON spec.",
    )


class LocationInput(BaseModel):
    """Flexible location input — accepts GeoJSON geometry or a text address."""

    geometry: GeoJSONGeometry | None = Field(
        None,
        description="GeoJSON geometry for the area of interest.",
    )
    address: str | None = Field(
        None,
        description="Text address or place name (will be geocoded).",
    )


class DateRange(BaseModel):
    """Date range filter."""

    start: datetime = Field(..., description="Start date (inclusive).")
    end: datetime = Field(..., description="End date (inclusive).")


class DeliveryOptions(BaseModel):
    """Options for imagery delivery."""

    format: DeliveryFormat = Field(
        default=DeliveryFormat.GEOTIFF,
        description="Desired delivery format.",
    )
    projection: str = Field(
        default="EPSG:4326",
        description="Target coordinate reference system.",
    )


class PriceBreakdown(BaseModel):
    """Itemized price information."""

    subtotal: float = Field(..., description="Base price in USD.")
    processing_fee: float = Field(0.0, description="Processing fee in USD.")
    total: float = Field(..., description="Total price in USD.")
    currency: str = Field("USD", description="Currency code.")


class PaginationInfo(BaseModel):
    """Pagination metadata for list endpoints."""

    has_more: bool = Field(..., description="Whether more results are available.")
    next_offset: str | None = Field(
        None,
        description="Opaque token to pass as page_token for the next page.",
    )
    total_count: int | None = Field(
        None,
        description="Total number of results (if known).",
    )


# ---------------------------------------------------------------------------
# Tool Input Models
# ---------------------------------------------------------------------------


# --- Search & Discovery ---


class SearchArchiveInput(BaseModel):
    """Input for search_archive tool."""

    location: LocationInput = Field(..., description="Area of interest.")
    date_range: DateRange | None = Field(None, description="Date range filter.")
    resolution_min: float | None = Field(
        None,
        description="Minimum resolution in meters.",
    )
    sensor_type: SensorType | None = Field(None, description="Filter by sensor type.")
    cloud_cover_max: float | None = Field(
        None,
        description="Maximum acceptable cloud cover percentage (0-100).",
        ge=0,
        le=100,
    )
    open_data: bool | None = Field(
        None,
        description="If true, return only free/open-data results.",
    )
    page_token: str | None = Field(
        None,
        description="Pagination token from a previous search response.",
    )


class GetArchiveDetailsInput(BaseModel):
    """Input for get_archive_details tool."""

    archive_id: str = Field(..., description="Unique identifier of the archive image.")


class ExploreProvidersInput(BaseModel):
    """Input for explore_providers tool."""

    location: LocationInput | None = Field(
        None,
        description="Optional location to filter providers by coverage.",
    )
    sensor_type: SensorType | None = Field(
        None,
        description="Optional sensor type filter.",
    )


# --- Pricing & Feasibility ---


class EstimateArchivePriceInput(BaseModel):
    """Input for estimate_archive_price tool."""

    archive_id: str = Field(..., description="Archive image ID to price.")
    delivery_options: DeliveryOptions | None = Field(
        None,
        description="Delivery format and projection preferences.",
    )


class GetTaskingQuoteInput(BaseModel):
    """Input for get_tasking_quote tool."""

    location: LocationInput = Field(
        ...,
        description="Area of interest for the new capture.",
    )
    resolution: float = Field(
        ...,
        description="Desired resolution in meters.",
    )
    sensor_type: SensorType | None = Field(None, description="Preferred sensor type.")
    time_window: DateRange | None = Field(
        None,
        description="Acceptable capture window.",
    )


class AnalyzeFeasibilityInput(BaseModel):
    """Input for analyze_feasibility tool."""

    location: LocationInput = Field(..., description="Area of interest.")
    time_window: DateRange | None = Field(None, description="Desired capture window.")
    resolution: float | None = Field(
        None,
        description="Target resolution in meters.",
    )


class ComparePricingInput(BaseModel):
    """Input for compare_pricing tool."""

    location: LocationInput = Field(..., description="Area of interest.")
    resolution_options: list[float] = Field(
        ...,
        description="List of resolution values (meters) to compare.",
    )


# --- Order Management ---


class PlaceArchiveOrderInput(BaseModel):
    """Input for place_archive_order tool."""

    archive_id: str = Field(..., description="Archive image ID to order.")
    delivery_options: DeliveryOptions | None = Field(
        None,
        description="Delivery format and projection preferences.",
    )
    confirmed: bool = Field(
        False,
        description=(
            "Must be true to execute the order. If false or omitted, returns a price "
            "preview and requires the user to confirm before proceeding."
        ),
    )
    webhook_url: str | None = Field(
        None,
        description="Optional callback URL for order status updates. SkyFi will POST to this URL on every status change.",
    )


class PlaceTaskingOrderInput(BaseModel):
    """Input for place_tasking_order tool."""

    location: LocationInput = Field(
        ...,
        description="Area of interest for the tasking order.",
    )
    window_start: datetime = Field(
        ...,
        description="Capture window start (ISO 8601 datetime, UTC).",
    )
    window_end: datetime = Field(
        ...,
        description="Capture window end (ISO 8601 datetime, UTC).",
    )
    product_type: str = Field(
        "DAY",
        description="Product type: DAY, SAR, MULTISPECTRAL, HYPERSPECTRAL, etc.",
    )
    resolution: str = Field(
        "HIGH",
        description="Resolution tier: LOW, MEDIUM, HIGH, VERY HIGH, SUPER HIGH, ULTRA HIGH.",
    )
    confirmed: bool = Field(
        False,
        description=(
            "Must be true to execute the order. If false or omitted, returns a price "
            "preview and requires the user to confirm."
        ),
    )
    webhook_url: str | None = Field(
        None,
        description="Optional callback URL for order status updates. SkyFi will POST to this URL on every status change.",
    )


class GetOrderStatusInput(BaseModel):
    """Input for get_order_status tool."""

    order_id: str = Field(..., description="Order ID to check.")


class ListOrdersInput(BaseModel):
    """Input for list_orders tool."""

    status: OrderStatus | None = Field(None, description="Filter by order status.")
    date_range: DateRange | None = Field(None, description="Filter by order date.")
    page: int = Field(1, description="Page number (1-indexed).", ge=1)


class GetOrderImagesInput(BaseModel):
    """Input for get_order_images tool."""

    order_id: str = Field(..., description="Order ID to fetch imagery for.")


# --- Monitoring & Notifications ---


class SetupAOIMonitoringInput(BaseModel):
    """Input for setup_aoi_monitoring tool."""

    location: LocationInput = Field(
        ...,
        description="GeoJSON area to monitor for new imagery.",
    )
    resolution_min: float | None = Field(
        None,
        description="Minimum resolution threshold in meters.",
    )
    notification_url: str | None = Field(
        None,
        description="Webhook URL for push notifications.",
    )


class DeleteMonitorInput(BaseModel):
    """Input for delete_monitor tool."""

    monitor_id: str = Field(..., description="Monitor ID to remove.")


class GetWebhookStatusInput(BaseModel):
    """Input for get_webhook_status tool."""

    subscription_id: str = Field(..., description="Webhook subscription ID.")


# --- Geospatial Utilities ---


class GeocodeInput(BaseModel):
    """Input for geocode tool."""

    query: str = Field(
        ...,
        description="Address or place name to geocode.",
    )


class ReverseGeocodeInput(BaseModel):
    """Input for reverse_geocode tool."""

    lat: float = Field(..., description="Latitude.", ge=-90, le=90)
    lon: float = Field(..., description="Longitude.", ge=-180, le=180)


class SearchPOIsInput(BaseModel):
    """Input for search_pois tool."""

    location: LocationInput = Field(..., description="Center point for POI search.")
    category: POICategory | None = Field(None, description="POI category filter.")
    radius: float = Field(
        1000,
        description="Search radius in meters.",
        gt=0,
        le=50000,
    )


class GetAreaBoundaryInput(BaseModel):
    """Input for get_area_boundary tool."""

    name: str = Field(
        ...,
        description="Name of the area (city, park, administrative region).",
    )
    admin_level: int | None = Field(
        None,
        description="OSM admin level (2=country, 4=state, 6=county, 8=city).",
        ge=1,
        le=11,
    )


# ---------------------------------------------------------------------------
# Tool Output Models
# ---------------------------------------------------------------------------


class ArchiveResult(BaseModel):
    """A single archive imagery result."""

    archive_id: str = Field(..., description="Unique image identifier.")
    provider: str = Field(..., description="Imagery provider name.")
    sensor_type: SensorType = Field(..., description="Sensor type.")
    resolution: float = Field(..., description="Ground resolution in meters.")
    capture_date: datetime = Field(..., description="Date of image capture.")
    cloud_cover: float | None = Field(None, description="Cloud cover percentage.")
    geometry: GeoJSONGeometry = Field(..., description="Image footprint geometry.")
    thumbnail_url: str | None = Field(None, description="Preview thumbnail URL.")
    open_data: bool = Field(False, description="Whether the image is free/open-data.")


class SearchArchiveOutput(BaseModel):
    """Output for search_archive tool."""

    results: list[ArchiveResult] = Field(default_factory=list, description="Matching images.")
    pagination: PaginationInfo = Field(..., description="Pagination metadata.")


class ArchiveDetailsOutput(BaseModel):
    """Output for get_archive_details tool."""

    archive_id: str
    provider: str
    sensor_type: SensorType
    resolution: float
    capture_date: datetime
    cloud_cover: float | None = None
    geometry: GeoJSONGeometry
    thumbnail_url: str | None = Field(None, description="Preview thumbnail URL.")
    bands: list[str] = Field(default_factory=list, description="Spectral bands available.")
    file_size_mb: float | None = None
    license: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata.")


class ProviderInfo(BaseModel):
    """Information about an imagery provider."""

    provider_id: str
    name: str
    sensor_types: list[SensorType]
    resolution_range: tuple[float, float] = Field(
        ...,
        description="(min, max) resolution in meters.",
    )
    coverage_description: str | None = None


class ExploreProvidersOutput(BaseModel):
    """Output for explore_providers tool."""

    providers: list[ProviderInfo]


class EstimateArchivePriceOutput(BaseModel):
    """Output for estimate_archive_price tool."""

    archive_id: str
    price: PriceBreakdown
    delivery_options: DeliveryOptions
    estimated_delivery_time: str | None = Field(
        None,
        description="Estimated delivery time (e.g. '2-4 hours').",
    )


class TaskingQuoteOutput(BaseModel):
    """Output for get_tasking_quote tool."""

    quote_id: str = Field(..., description="Unique quote identifier for ordering.")
    price: PriceBreakdown
    feasibility_score: float = Field(
        ...,
        description="0.0-1.0 score indicating capture feasibility.",
        ge=0,
        le=1,
    )
    estimated_capture_window: DateRange | None = None
    provider: str | None = None
    resolution: float | None = None
    expires_at: datetime | None = Field(
        None,
        description="When this quote expires.",
    )


class FeasibilityAnalysis(BaseModel):
    """Output for analyze_feasibility tool."""

    feasibility_score: float = Field(..., ge=0, le=1)
    cloud_forecast: str | None = Field(
        None,
        description="Cloud cover forecast for the area.",
    )
    satellite_passes: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Upcoming satellite passes over the AOI.",
    )
    capture_windows: list[DateRange] = Field(
        default_factory=list,
        description="Recommended capture windows.",
    )
    recommendations: str | None = None


class PricingComparison(BaseModel):
    """A single row in a pricing comparison."""

    provider: str
    resolution: float
    price: PriceBreakdown
    sensor_type: SensorType


class ComparePricingOutput(BaseModel):
    """Output for compare_pricing tool."""

    comparisons: list[PricingComparison]
    recommended: PricingComparison | None = Field(
        None,
        description="Best value option based on price/resolution ratio.",
    )


class OrderConfirmationPreview(BaseModel):
    """Returned when confirmed=false — asks the user to confirm."""

    order_type: str = Field(..., description="'archive' or 'tasking'.")
    price: PriceBreakdown
    details: dict[str, Any] = Field(
        ...,
        description="Order details for user review.",
    )
    message: str = Field(
        ...,
        description="Human-readable confirmation message.",
    )


class OrderConfirmation(BaseModel):
    """Returned when confirmed=true and order is placed successfully."""

    order_id: str
    order_url: str = Field(
        ...,
        description="Direct link to the order on SkyFi (e.g. https://app.skyfi.com/orders/{id}).",
    )
    status: OrderStatus
    price: PriceBreakdown
    estimated_delivery: str | None = None
    message: str


class PlaceOrderOutput(BaseModel):
    """Output for place_archive_order / place_tasking_order tools."""

    preview: OrderConfirmationPreview | None = Field(
        None,
        description="Set when confirmed=false. User must review and re-call with confirmed=true.",
    )
    confirmation: OrderConfirmation | None = Field(
        None,
        description="Set when confirmed=true and order is placed.",
    )


class OrderStatusOutput(BaseModel):
    """Output for get_order_status tool."""

    order_id: str
    order_url: str = Field(
        "",
        description="Direct link to the order on SkyFi (e.g. https://app.skyfi.com/orders/{id}).",
    )
    status: OrderStatus
    created_at: datetime | None = None
    updated_at: datetime | None = None
    price: PriceBreakdown | None = None
    delivery_urls: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _empty_str_to_none(cls, v: Any) -> Any:
        if v == "":
            return None
        return v


class ListOrdersOutput(BaseModel):
    """Output for list_orders tool."""

    orders: list[OrderStatusOutput]
    pagination: PaginationInfo


class OrderImagesOutput(BaseModel):
    """Output for get_order_images tool."""

    order_id: str
    images: list[dict[str, Any]] = Field(
        ...,
        description="List of image download entries with url, format, size_mb.",
    )


class MonitorInfo(BaseModel):
    """Information about an active AOI monitor."""

    monitor_id: str
    location: GeoJSONGeometry
    resolution_min: float | None = None
    notification_url: str | None = None
    created_at: datetime
    status: str = Field("active", description="Monitor status.")


class SetupMonitorOutput(BaseModel):
    """Output for setup_aoi_monitoring tool."""

    monitor: MonitorInfo
    message: str


class ListMonitorsOutput(BaseModel):
    """Output for list_monitors tool."""

    monitors: list[MonitorInfo]


class DeleteMonitorOutput(BaseModel):
    """Output for delete_monitor tool."""

    monitor_id: str
    deleted: bool
    message: str


class WebhookStatusOutput(BaseModel):
    """Output for get_webhook_status tool."""

    subscription_id: str
    status: str
    last_delivery_at: datetime | None = None
    delivery_count: int = 0
    failure_count: int = 0


class Notification(BaseModel):
    """A single notification entry."""

    notification_id: str
    type: str = Field(..., description="Notification type (e.g. 'new_imagery').")
    monitor_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class CheckNotificationsOutput(BaseModel):
    """Output for check_notifications tool."""

    notifications: list[Notification]
    unread_count: int = 0


class GeocodeResult(BaseModel):
    """A single geocoding result."""

    lat: float
    lon: float
    display_name: str
    geometry: GeoJSONGeometry | None = None
    osm_type: str | None = None
    osm_id: int | None = None
    importance: float | None = None


class GeocodeOutput(BaseModel):
    """Output for geocode tool."""

    results: list[GeocodeResult]


class ReverseGeocodeOutput(BaseModel):
    """Output for reverse_geocode tool."""

    address: str
    lat: float
    lon: float
    details: dict[str, Any] = Field(default_factory=dict)


class POIResult(BaseModel):
    """A single point-of-interest result."""

    name: str
    category: str
    lat: float
    lon: float
    distance_m: float | None = None
    osm_id: int | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class SearchPOIsOutput(BaseModel):
    """Output for search_pois tool."""

    results: list[POIResult]


class AreaBoundaryOutput(BaseModel):
    """Output for get_area_boundary tool."""

    name: str
    geometry: GeoJSONGeometry
    admin_level: int | None = None
    osm_id: int | None = None


# ---------------------------------------------------------------------------
# Tool Protocol Definitions
# ---------------------------------------------------------------------------


@runtime_checkable
class SearchTools(Protocol):
    """Protocol for search & discovery tools."""

    async def search_archive(self, input: SearchArchiveInput) -> SearchArchiveOutput: ...

    async def get_archive_details(self, input: GetArchiveDetailsInput) -> ArchiveDetailsOutput: ...

    async def explore_providers(self, input: ExploreProvidersInput) -> ExploreProvidersOutput: ...


@runtime_checkable
class PricingTools(Protocol):
    """Protocol for pricing & feasibility tools."""

    async def estimate_archive_price(
        self, input: EstimateArchivePriceInput
    ) -> EstimateArchivePriceOutput: ...

    async def get_tasking_quote(self, input: GetTaskingQuoteInput) -> TaskingQuoteOutput: ...

    async def analyze_feasibility(
        self, input: AnalyzeFeasibilityInput
    ) -> FeasibilityAnalysis: ...

    async def compare_pricing(self, input: ComparePricingInput) -> ComparePricingOutput: ...


@runtime_checkable
class OrderTools(Protocol):
    """Protocol for order management tools."""

    async def place_archive_order(self, input: PlaceArchiveOrderInput) -> PlaceOrderOutput: ...

    async def place_tasking_order(self, input: PlaceTaskingOrderInput) -> PlaceOrderOutput: ...

    async def get_order_status(self, input: GetOrderStatusInput) -> OrderStatusOutput: ...

    async def list_orders(self, input: ListOrdersInput) -> ListOrdersOutput: ...

    async def get_order_images(self, input: GetOrderImagesInput) -> OrderImagesOutput: ...


@runtime_checkable
class MonitoringTools(Protocol):
    """Protocol for monitoring & notification tools."""

    async def setup_aoi_monitoring(
        self, input: SetupAOIMonitoringInput
    ) -> SetupMonitorOutput: ...

    async def list_monitors(self) -> ListMonitorsOutput: ...

    async def delete_monitor(self, input: DeleteMonitorInput) -> DeleteMonitorOutput: ...

    async def get_webhook_status(self, input: GetWebhookStatusInput) -> WebhookStatusOutput: ...

    async def check_notifications(self) -> CheckNotificationsOutput: ...


@runtime_checkable
class GeoTools(Protocol):
    """Protocol for OpenStreetMap geospatial utility tools."""

    async def geocode(self, input: GeocodeInput) -> GeocodeOutput: ...

    async def reverse_geocode(self, input: ReverseGeocodeInput) -> ReverseGeocodeOutput: ...

    async def search_pois(self, input: SearchPOIsInput) -> SearchPOIsOutput: ...

    async def get_area_boundary(self, input: GetAreaBoundaryInput) -> AreaBoundaryOutput: ...
