"""
SkyFi MCP Server — Local stdio transport (FastMCP)

Registers all 21 MCP tools with proper annotations and delegates each call
to the corresponding function in ``skyfi_mcp.tools``.

Phase 3 Integration: Bridges FastMCP's raw-parameter tool handlers with
Agent A's typed tool functions that expect (client, input_model, api_key).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, cast

from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from mcp.types import TextContent, ToolAnnotations
from skyfi_mcp.client.osm import OSMClient
from skyfi_mcp.client.skyfi import SkyFiClient
from skyfi_mcp.thumbnails import encode_thumbnail_base64, fetch_thumbnails
from skyfi_mcp.tools import geo as geo_tools
from skyfi_mcp.tools import monitoring as monitoring_tools
from skyfi_mcp.tools import orders as order_tools
from skyfi_mcp.tools import pricing as pricing_tools
from skyfi_mcp.tools import search as search_tools
from skyfi_mcp.validation import (
    validate_address,
    validate_array_length,
    validate_geojson_geometry,
)

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
    GeoJSONGeometry,
    GetArchiveDetailsInput,
    GetAreaBoundaryInput,
    GetOrderImagesInput,
    GetOrderStatusInput,
    GetTaskingQuoteInput,
    GetWebhookStatusInput,
    ListOrdersInput,
    LocationInput,
    OrderStatus,
    PlaceArchiveOrderInput,
    PlaceTaskingOrderInput,
    POICategory,
    ReverseGeocodeInput,
    SearchArchiveInput,
    SearchPOIsInput,
    SensorType,
    SetupAOIMonitoringInput,
)
from packages.server.local.config import load_config

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
        return cast("dict[str, Any]", result.model_dump(mode="json"))
    return cast("dict[str, Any]", result)


def _wkt_centroid(wkt: str) -> tuple[float, float] | None:
    """Extract approximate centroid (lat, lon) from a WKT string."""
    from skyfi_mcp.client.wkt import wkt_to_geojson

    try:
        geom = wkt_to_geojson(wkt)
    except (ValueError, IndexError):
        return None

    coords = geom.get("coordinates", [])
    if geom["type"] == "Point":
        return (coords[1], coords[0])

    # Polygon / MultiPolygon — average the outer ring vertices
    if geom["type"] == "MultiPolygon":
        flat = coords[0][0]  # first polygon, outer ring
    elif geom["type"] == "Polygon":
        flat = coords[0]  # outer ring
    else:
        return None

    if not flat:
        return None
    lats = [p[1] for p in flat]
    lons = [p[0] for p in flat]
    return (sum(lats) / len(lats), sum(lons) / len(lons))


async def _resolve_location_name(
    order: dict[str, Any],
    osm_client: OSMClient,
) -> str:
    """Best-effort location name for an order dict."""
    # Priority 1: already have a label
    if order.get("location_name"):
        return order["location_name"]

    # Priority 2: reverse geocode the AOI centroid
    aoi_wkt = order.get("metadata", {}).get("aoi", "")
    if not aoi_wkt:
        return ""

    centroid = _wkt_centroid(aoi_wkt)
    if centroid is None:
        return ""

    try:
        result = await osm_client.reverse_geocode(centroid[0], centroid[1])
        d = result.details
        city = d.get("city") or d.get("town") or d.get("village") or ""
        state = d.get("state", "")
        if city and state:
            return f"{city}, {state}"
        if city:
            return city
        cc = d.get("country_code", "").upper()
        if state and cc:
            return f"{state}, {cc}"
        return state or result.address.split(",")[0].strip() if result.address else ""
    except Exception:
        return ""


def _inject_thumbnail_data_uris(
    result_dict: dict[str, Any],
    thumbnails: dict[str, Any],
) -> None:
    """Embed base64 data URIs into result dicts and strip external thumbnail_url.

    Mutates *result_dict* in place.  Works for both search (list of results)
    and detail (single result) payloads.
    """
    results = result_dict.get("results")
    if isinstance(results, list):
        # search_archive — list of results
        for item in results:
            aid = item.get("archive_id")
            if aid and aid in thumbnails:
                thumb = thumbnails[aid]
                mime = f"image/{thumb.format}"
                b64 = encode_thumbnail_base64(thumb.data)
                item["thumbnail_data_uri"] = f"data:{mime};base64,{b64}"
            item.pop("thumbnail_url", None)
    else:
        # get_archive_details — single result at top level
        aid = result_dict.get("archive_id")
        if aid and aid in thumbnails:
            thumb = thumbnails[aid]
            mime = f"image/{thumb.format}"
            b64 = encode_thumbnail_base64(thumb.data)
            result_dict["thumbnail_data_uri"] = f"data:{mime};base64,{b64}"
        result_dict.pop("thumbnail_url", None)


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
    include_thumbnails: bool = True,
) -> list[TextContent | Image]:
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
    result_dict = _to_dict(result)

    thumbs: dict[str, Any] = {}
    if include_thumbnails:
        thumb_urls = [
            (r.archive_id, r.thumbnail_url)
            for r in result.results
            if r.thumbnail_url
        ]
        if thumb_urls:
            thumbs = await fetch_thumbnails(thumb_urls, max_count=5)

    # Embed data URIs and strip external thumbnail_url from all results
    _inject_thumbnail_data_uris(result_dict, thumbs)

    content: list[TextContent | Image] = [
        TextContent(type="text", text=json.dumps(result_dict))
    ]

    # Keep Image content blocks for Claude's vision model
    for _archive_id, thumb in thumbs.items():
        content.append(Image(data=thumb.data, format=thumb.format))

    return content


@mcp.tool(
    name="get_archive_details",
    description=(
        "Get detailed metadata for a specific archive image, including "
        "bands, file size, license, and full geometry."
    ),
    annotations=_READ_ONLY,
)
async def get_archive_details(
    archive_id: str,
    include_thumbnails: bool = True,
) -> list[TextContent | Image]:
    """Retrieve full details for a single archive image."""
    input_model = GetArchiveDetailsInput(archive_id=archive_id)
    result = await search_tools.get_archive_details(_skyfi_client, input_model, _api_key)
    result_dict = _to_dict(result)

    thumbs: dict[str, Any] = {}
    if include_thumbnails and result.thumbnail_url:
        thumbs = await fetch_thumbnails(
            [(result.archive_id, result.thumbnail_url)], max_count=1
        )

    # Embed data URI and strip external thumbnail_url
    _inject_thumbnail_data_uris(result_dict, thumbs)

    content: list[TextContent | Image] = [
        TextContent(type="text", text=json.dumps(result_dict))
    ]

    # Keep Image content block for Claude's vision model
    for _archive_id, thumb in thumbs.items():
        content.append(Image(data=thumb.data, format=thumb.format))

    return content


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
        "confirmed=true to execute the order. "
        "When showing the preview, display the thumbnail image, location, "
        "provider, area, estimated delivery, and price breakdown as a "
        "checkout summary. Ask the user to confirm before proceeding."
    ),
    annotations=_DESTRUCTIVE,
)
async def place_archive_order(
    archive_id: str,
    delivery_options: dict[str, Any] | None = None,
    confirmed: bool = False,
    webhook_url: str | None = None,
) -> list[TextContent | Image] | dict[str, Any]:
    """Place an archive order (requires human confirmation)."""
    input_model = PlaceArchiveOrderInput(
        archive_id=archive_id,
        delivery_options=_build_delivery_options(delivery_options),
        confirmed=confirmed,
        webhook_url=webhook_url,
    )
    result = await order_tools.place_archive_order(_skyfi_client, input_model, _api_key)
    result_dict = _to_dict(result)

    # For preview: enrich with thumbnail + location
    if result.preview is not None:
        archive = await _skyfi_client.get_archive(_api_key, archive_id=archive_id)
        thumb_urls = archive.get("thumbnailUrls", {})
        thumb_url = next(iter(thumb_urls.values()), None)

        content: list[TextContent | Image] = []

        if thumb_url:
            thumbs = await fetch_thumbnails([(archive_id, thumb_url)], max_count=1)
            thumb = thumbs.get(archive_id)
            if thumb:
                mime = f"image/{thumb.format}"
                b64 = encode_thumbnail_base64(thumb.data)
                result_dict["preview"]["details"]["thumbnail_data_uri"] = (
                    f"data:{mime};base64,{b64}"
                )
                content.append(Image(data=thumb.data, format=thumb.format))

        # Resolve location from footprint
        footprint = archive.get("footprint", "")
        if footprint:
            loc = await _resolve_location_name(
                {"metadata": {"aoi": footprint}}, _osm_client
            )
            if loc:
                result_dict["preview"]["details"]["location_name"] = loc

        content.insert(0, TextContent(type="text", text=json.dumps(result_dict)))
        return content

    return result_dict


@mcp.tool(
    name="place_tasking_order",
    description=(
        "Place a tasking order for new satellite imagery capture. "
        "Requires location, capture window, product type, and resolution. "
        "Requires two-step confirmation: call first with confirmed=false "
        "to review the price, then with confirmed=true to execute. "
        "When showing the preview, display the location, capture window, "
        "product details, and price breakdown as a checkout summary."
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
    webhook_url: str | None = None,
) -> dict[str, Any]:
    """Place a tasking order (requires human confirmation)."""
    input_model = PlaceTaskingOrderInput(
        location=_build_location(location),
        window_start=datetime.fromisoformat(window_start),
        window_end=datetime.fromisoformat(window_end),
        product_type=product_type,
        resolution=resolution,
        confirmed=confirmed,
        webhook_url=webhook_url,
    )
    result = await order_tools.place_tasking_order(_skyfi_client, input_model, _api_key)
    result_dict = _to_dict(result)

    # For preview: enrich with location name from input geometry
    if result.preview is not None:
        geom = location.get("geometry")
        if geom:
            from skyfi_mcp.client.wkt import geojson_to_wkt

            aoi_wkt = geojson_to_wkt(geom)
            if aoi_wkt:
                loc = await _resolve_location_name(
                    {"metadata": {"aoi": aoi_wkt}}, _osm_client
                )
                if loc:
                    result_dict["preview"]["details"]["location_name"] = loc

    return result_dict


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
        "List your orders with location info and direct links. "
        "Each order includes order_url — always present order_id as a "
        "clickable markdown link using order_url. Include the location_name "
        "column. Do not show a status column."
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
    result_dict = _to_dict(result)

    # Resolve location names (best-effort, cap at 3 reverse geocodes for latency)
    max_geocode = 3
    geocoded = 0
    for order in result_dict.get("orders", []):
        if (
            not order.get("location_name")
            and order.get("metadata", {}).get("aoi")
            and geocoded < max_geocode
        ):
            order["location_name"] = await _resolve_location_name(order, _osm_client)
            geocoded += 1
        # Remove status from serialized output
        order.pop("status", None)

    return result_dict


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
