"""
SkyFi MCP Server — Local stdio transport (FastMCP)

Registers all 21 MCP tools with proper annotations and delegates each call
to the corresponding function in ``skyfi_mcp.tools``.

Phase 3 Integration: Bridges FastMCP's raw-parameter tool handlers with
Agent A's typed tool functions that expect (client, input_model, api_key).
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from packages.server.local.config import load_config
from skyfi_mcp.client.osm import OSMClient
from skyfi_mcp.client.skyfi import SkyFiClient
from skyfi_mcp.tools import geo as geo_tools
from skyfi_mcp.tools import monitoring as monitoring_tools
from skyfi_mcp.tools import orders as order_tools
from skyfi_mcp.tools import pricing as pricing_tools
from skyfi_mcp.tools import search as search_tools

# Import input models for constructing typed inputs from raw params
from interfaces import (
    AnalyzeFeasibilityInput,
    ComparePricingInput,
    DateRange,
    DeleteMonitorInput,
    DeliveryOptions,
    EstimateArchivePriceInput,
    ExploreProvidersInput,
    GeocodeInput,
    GetArchiveDetailsInput,
    GetAreaBoundaryInput,
    GetOrderImagesInput,
    GetOrderStatusInput,
    GetWebhookStatusInput,
    ListOrdersInput,
    LocationInput,
    GeoJSONGeometry,
    GetTaskingQuoteInput,
    OrderStatus,
    PlaceArchiveOrderInput,
    PlaceTaskingOrderInput,
    ReverseGeocodeInput,
    SearchArchiveInput,
    SearchPOIsInput,
    SensorType,
    SetupAOIMonitoringInput,
    POICategory,
)

from skyfi_mcp.validation import (
    validate_array_length,
    validate_geojson_geometry,
    validate_address,
)

# ---------------------------------------------------------------------------
# Annotation presets
# ---------------------------------------------------------------------------

_READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)

_READ_ONLY_NON_IDEMPOTENT = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)

_MUTATING = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)

_DESTRUCTIVE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)

# ---------------------------------------------------------------------------
# Server + clients
# ---------------------------------------------------------------------------

mcp = FastMCP("skyfi_mcp")

# Load config and create clients once at import time.
_config = load_config()
_api_key: str = _config.api_key
_skyfi_client = SkyFiClient(base_url=_config.api_base_url, auth_header=_config.auth_header)
_osm_client = OSMClient()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_location(location: dict[str, Any]) -> LocationInput:
    """Build a LocationInput from a raw dict, with validation."""
    geometry = None
    address = None
    if "geometry" in location:
        g = location["geometry"]
        geometry = GeoJSONGeometry(type=g["type"], coordinates=g["coordinates"])
    if "address" in location:
        address = validate_address(location["address"])
    # If top-level has type+coordinates, treat as geometry directly
    if "type" in location and "coordinates" in location and geometry is None:
        geometry = GeoJSONGeometry(type=location["type"], coordinates=location["coordinates"])
    # Handle plain {"lat": ..., "lon": ...} dicts (LLMs frequently use this format)
    if geometry is None and "lat" in location and "lon" in location:
        geometry = GeoJSONGeometry(
            type="Point", coordinates=[float(location["lon"]), float(location["lat"])]
        )
    # Validate GeoJSON geometry coordinates
    if geometry is not None:
        validate_geojson_geometry(geometry)
    return LocationInput(geometry=geometry, address=address)


def _build_date_range(dr: dict[str, Any] | None) -> DateRange | None:
    """Build a DateRange from a raw dict."""
    if dr is None:
        return None
    return DateRange(start=dr["start"], end=dr["end"])


def _build_delivery_options(opts: dict[str, Any] | None) -> DeliveryOptions | None:
    """Build DeliveryOptions from a raw dict."""
    if opts is None:
        return None
    return DeliveryOptions(**opts)


def _to_dict(result: Any) -> dict[str, Any]:
    """Serialize a Pydantic model to dict for MCP response."""
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    return result


# ---------------------------------------------------------------------------
# Search & Discovery tools
# ---------------------------------------------------------------------------


@mcp.tool(
    name="search_archive",
    description=(
        "Search SkyFi's satellite imagery archive by location, date range, "
        "resolution, sensor type, and cloud cover. Returns matching imagery "
        "results with pagination."
    ),
    annotations=_READ_ONLY,
)
async def search_archive(
    location: dict[str, Any],
    date_range: dict[str, Any] | None = None,
    resolution_min: float | None = None,
    sensor_type: str | None = None,
    cloud_cover_max: float | None = None,
    open_data: bool | None = None,
    page_token: str | None = None,
) -> dict[str, Any]:
    """Search the SkyFi archive for satellite imagery."""
    input_model = SearchArchiveInput(
        location=_build_location(location),
        date_range=_build_date_range(date_range),
        resolution_min=resolution_min,
        sensor_type=SensorType(sensor_type) if sensor_type else None,
        cloud_cover_max=cloud_cover_max,
        open_data=open_data,
        page_token=page_token,
    )
    result = await search_tools.search_archive(_skyfi_client, input_model, _api_key)
    return _to_dict(result)


@mcp.tool(
    name="get_archive_details",
    description=(
        "Get detailed metadata for a specific archive image, including "
        "bands, file size, license, and full geometry."
    ),
    annotations=_READ_ONLY,
)
async def get_archive_details(archive_id: str) -> dict[str, Any]:
    """Retrieve full details for a single archive image."""
    input_model = GetArchiveDetailsInput(archive_id=archive_id)
    result = await search_tools.get_archive_details(_skyfi_client, input_model, _api_key)
    return _to_dict(result)


@mcp.tool(
    name="explore_providers",
    description=(
        "List available satellite imagery providers, optionally filtered "
        "by location and sensor type."
    ),
    annotations=_READ_ONLY,
)
async def explore_providers(
    location: dict[str, Any] | None = None,
    sensor_type: str | None = None,
) -> dict[str, Any]:
    """Explore available imagery providers."""
    loc = _build_location(location) if location else None
    input_model = ExploreProvidersInput(
        location=loc,
        sensor_type=SensorType(sensor_type) if sensor_type else None,
    )
    result = await search_tools.explore_providers(_skyfi_client, input_model, _api_key)
    return _to_dict(result)


# ---------------------------------------------------------------------------
# Pricing & Feasibility tools
# ---------------------------------------------------------------------------


@mcp.tool(
    name="estimate_archive_price",
    description=(
        "Get an estimated price for purchasing an archive image, "
        "including processing fees and delivery options."
    ),
    annotations=_READ_ONLY,
)
async def estimate_archive_price(
    archive_id: str,
    delivery_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Estimate the price for an archive image."""
    input_model = EstimateArchivePriceInput(
        archive_id=archive_id,
        delivery_options=_build_delivery_options(delivery_options),
    )
    result = await pricing_tools.estimate_archive_price(_skyfi_client, input_model, _api_key)
    return _to_dict(result)


@mcp.tool(
    name="get_tasking_quote",
    description=(
        "Request a quote for a new satellite capture (tasking order) over "
        "a specified area, resolution, and time window."
    ),
    annotations=_READ_ONLY_NON_IDEMPOTENT,
)
async def get_tasking_quote(
    location: dict[str, Any],
    resolution: float,
    sensor_type: str | None = None,
    time_window: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Get a tasking quote for a new satellite capture."""
    input_model = GetTaskingQuoteInput(
        location=_build_location(location),
        resolution=resolution,
        sensor_type=SensorType(sensor_type) if sensor_type else None,
        time_window=_build_date_range(time_window),
    )
    result = await pricing_tools.get_tasking_quote(_skyfi_client, input_model, _api_key)
    return _to_dict(result)


@mcp.tool(
    name="analyze_feasibility",
    description=(
        "Analyze the feasibility of capturing new imagery over an area, "
        "including cloud forecasts, satellite passes, and recommended windows."
    ),
    annotations=_READ_ONLY_NON_IDEMPOTENT,
)
async def analyze_feasibility(
    location: dict[str, Any],
    time_window: dict[str, Any] | None = None,
    resolution: float | None = None,
) -> dict[str, Any]:
    """Analyze capture feasibility for an area of interest."""
    input_model = AnalyzeFeasibilityInput(
        location=_build_location(location),
        time_window=_build_date_range(time_window),
        resolution=resolution,
    )
    result = await pricing_tools.analyze_feasibility(_skyfi_client, input_model, _api_key)
    return _to_dict(result)


@mcp.tool(
    name="compare_pricing",
    description=(
        "Compare prices across providers and resolution levels for a "
        "given area of interest. Returns a ranked list with a recommended option."
    ),
    annotations=_READ_ONLY,
)
async def compare_pricing(
    location: dict[str, Any],
    resolution_options: list[float],
) -> dict[str, Any]:
    """Compare pricing across providers and resolutions."""
    validate_array_length(resolution_options, "resolution_options")
    input_model = ComparePricingInput(
        location=_build_location(location),
        resolution_options=resolution_options,
    )
    result = await pricing_tools.compare_pricing(_skyfi_client, input_model, _api_key)
    return _to_dict(result)


# ---------------------------------------------------------------------------
# Order Management tools
# ---------------------------------------------------------------------------


@mcp.tool(
    name="place_archive_order",
    description=(
        "Place an order for an archive image. Requires two-step confirmation: "
        "call first with confirmed=false to preview the price, then with "
        "confirmed=true to execute the order."
    ),
    annotations=_DESTRUCTIVE,
)
async def place_archive_order(
    archive_id: str,
    delivery_options: dict[str, Any] | None = None,
    confirmed: bool = False,
) -> dict[str, Any]:
    """Place an archive order (requires human confirmation)."""
    input_model = PlaceArchiveOrderInput(
        archive_id=archive_id,
        delivery_options=_build_delivery_options(delivery_options),
        confirmed=confirmed,
    )
    result = await order_tools.place_archive_order(_skyfi_client, input_model, _api_key)
    return _to_dict(result)


@mcp.tool(
    name="place_tasking_order",
    description=(
        "Place a tasking order for new satellite imagery capture. "
        "Requires location, capture window, product type, and resolution. "
        "Requires two-step confirmation: call first with confirmed=false "
        "to review the price, then with confirmed=true to execute."
    ),
    annotations=_DESTRUCTIVE,
)
async def place_tasking_order(
    location: dict[str, Any],
    window_start: str,
    window_end: str,
    product_type: str = "DAY",
    resolution: str = "HIGH",
    confirmed: bool = False,
) -> dict[str, Any]:
    """Place a tasking order (requires human confirmation)."""
    input_model = PlaceTaskingOrderInput(
        location=_build_location(location),
        window_start=window_start,
        window_end=window_end,
        product_type=product_type,
        resolution=resolution,
        confirmed=confirmed,
    )
    result = await order_tools.place_tasking_order(_skyfi_client, input_model, _api_key)
    return _to_dict(result)


@mcp.tool(
    name="get_order_status",
    description="Check the current status and details of an existing order.",
    annotations=_READ_ONLY,
)
async def get_order_status(order_id: str) -> dict[str, Any]:
    """Get the status of an order."""
    input_model = GetOrderStatusInput(order_id=order_id)
    result = await order_tools.get_order_status(_skyfi_client, input_model, _api_key)
    return _to_dict(result)


@mcp.tool(
    name="list_orders",
    description=(
        "List your orders, optionally filtered by status and date range. "
        "Supports pagination."
    ),
    annotations=_READ_ONLY,
)
async def list_orders(
    status: str | None = None,
    date_range: dict[str, Any] | None = None,
    page: int = 1,
) -> dict[str, Any]:
    """List orders with optional filters."""
    input_model = ListOrdersInput(
        status=OrderStatus(status) if status else None,
        date_range=_build_date_range(date_range),
        page=page,
    )
    result = await order_tools.list_orders(_skyfi_client, input_model, _api_key)
    return _to_dict(result)


@mcp.tool(
    name="get_order_images",
    description="Retrieve download URLs for imagery delivered as part of an order.",
    annotations=_READ_ONLY,
)
async def get_order_images(order_id: str) -> dict[str, Any]:
    """Get delivered images for an order."""
    input_model = GetOrderImagesInput(order_id=order_id)
    result = await order_tools.get_order_images(_skyfi_client, input_model, _api_key)
    return _to_dict(result)


# ---------------------------------------------------------------------------
# Monitoring & Notification tools
# ---------------------------------------------------------------------------


@mcp.tool(
    name="setup_aoi_monitoring",
    description=(
        "Set up automated monitoring for new imagery over an area of interest. "
        "Optionally specify a webhook URL for push notifications."
    ),
    annotations=_MUTATING,
)
async def setup_aoi_monitoring(
    location: dict[str, Any],
    resolution_min: float | None = None,
    notification_url: str | None = None,
) -> dict[str, Any]:
    """Set up AOI monitoring for new imagery."""
    input_model = SetupAOIMonitoringInput(
        location=_build_location(location),
        resolution_min=resolution_min,
        notification_url=notification_url,
    )
    result = await monitoring_tools.setup_aoi_monitoring(_skyfi_client, input_model, _api_key)
    return _to_dict(result)


@mcp.tool(
    name="list_monitors",
    description="List all active AOI monitors on your account.",
    annotations=_READ_ONLY,
)
async def list_monitors() -> dict[str, Any]:
    """List all active monitors."""
    result = await monitoring_tools.list_monitors(_skyfi_client, _api_key)
    return _to_dict(result)


@mcp.tool(
    name="delete_monitor",
    description="Delete an existing AOI monitor by its ID.",
    annotations=_DESTRUCTIVE,
)
async def delete_monitor(monitor_id: str) -> dict[str, Any]:
    """Delete a monitor."""
    input_model = DeleteMonitorInput(monitor_id=monitor_id)
    result = await monitoring_tools.delete_monitor(_skyfi_client, input_model, _api_key)
    return _to_dict(result)


@mcp.tool(
    name="get_webhook_status",
    description=(
        "Check the delivery status and health of a webhook subscription, "
        "including delivery and failure counts."
    ),
    annotations=_READ_ONLY,
)
async def get_webhook_status(subscription_id: str) -> dict[str, Any]:
    """Get webhook subscription status."""
    input_model = GetWebhookStatusInput(subscription_id=subscription_id)
    result = await monitoring_tools.get_webhook_status(_skyfi_client, input_model, _api_key)
    return _to_dict(result)


@mcp.tool(
    name="check_notifications",
    description="Check for unread notifications (new imagery alerts, order updates).",
    annotations=_READ_ONLY,
)
async def check_notifications() -> dict[str, Any]:
    """Check for unread notifications."""
    result = await monitoring_tools.check_notifications(_skyfi_client, _api_key)
    return _to_dict(result)


# ---------------------------------------------------------------------------
# Geospatial Utility tools
# ---------------------------------------------------------------------------


@mcp.tool(
    name="geocode",
    description=(
        "Convert an address or place name to geographic coordinates. "
        "Uses OpenStreetMap Nominatim."
    ),
    annotations=_READ_ONLY,
)
async def geocode(query: str) -> dict[str, Any]:
    """Geocode an address or place name."""
    input_model = GeocodeInput(query=query)
    result = await geo_tools.geocode(_osm_client, input_model)
    return _to_dict(result)


@mcp.tool(
    name="reverse_geocode",
    description=(
        "Convert geographic coordinates (lat/lon) to a human-readable address. "
        "Uses OpenStreetMap Nominatim."
    ),
    annotations=_READ_ONLY,
)
async def reverse_geocode(lat: float, lon: float) -> dict[str, Any]:
    """Reverse-geocode coordinates to an address."""
    input_model = ReverseGeocodeInput(lat=lat, lon=lon)
    result = await geo_tools.reverse_geocode(_osm_client, input_model)
    return _to_dict(result)


@mcp.tool(
    name="search_pois",
    description=(
        "Search for points of interest (airports, ports, industrial areas, etc.) "
        "near a location within a given radius. Uses OpenStreetMap."
    ),
    annotations=_READ_ONLY,
)
async def search_pois(
    location: dict[str, Any],
    category: str | None = None,
    radius: float = 1000,
) -> dict[str, Any]:
    """Search for nearby points of interest."""
    input_model = SearchPOIsInput(
        location=_build_location(location),
        category=POICategory(category) if category else None,
        radius=radius,
    )
    result = await geo_tools.search_pois(_osm_client, input_model)
    return _to_dict(result)


@mcp.tool(
    name="get_area_boundary",
    description=(
        "Get the boundary polygon for a named area (city, park, country, etc.). "
        "Uses OpenStreetMap administrative boundaries."
    ),
    annotations=_READ_ONLY,
)
async def get_area_boundary(
    name: str,
    admin_level: int | None = None,
) -> dict[str, Any]:
    """Get the boundary for a named area."""
    input_model = GetAreaBoundaryInput(name=name, admin_level=admin_level)
    result = await geo_tools.get_area_boundary(_osm_client, input_model)
    return _to_dict(result)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the SkyFi MCP server over stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
