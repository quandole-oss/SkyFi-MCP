"""
Order Management tools.

Handles archive and tasking order placement with mandatory human confirmation,
order status queries, order listing, and delivered-image retrieval.

Real API endpoints:
  POST /order-archive   -- place archive order (needs aoi WKT + archiveId)
  POST /order-tasking    -- place tasking order (needs aoi WKT + window + product)
  GET  /orders           -- list orders
  GET  /orders/{id}      -- order details
  GET  /orders/{id}/{type} -- download deliverable

CRITICAL: ``place_archive_order`` and ``place_tasking_order`` must check that
``confirmed == True`` before executing. If ``confirmed`` is ``False`` (the
default), a preview is returned instead. Orders are NEVER auto-confirmed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from interfaces import (
    GetOrderImagesInput,
    GetOrderStatusInput,
    ListOrdersInput,
    ListOrdersOutput,
    OrderImagesOutput,
    OrderStatus,
    OrderStatusOutput,
    PaginationInfo,
    PlaceArchiveOrderInput,
    PlaceOrderOutput,
    PlaceTaskingOrderInput,
    PriceBreakdown,
)
from skyfi_mcp.client.wkt import geojson_to_wkt

if TYPE_CHECKING:
    from skyfi_mcp.client.skyfi import SkyFiClient
from skyfi_mcp.confirmation import (
    build_archive_order_preview,
    build_order_confirmation,
    build_tasking_order_preview,
    require_confirmation,
)

logger = logging.getLogger(__name__)


def _parse_price(raw: dict[str, Any]) -> PriceBreakdown:
    """Parse a PriceBreakdown from raw API JSON."""
    return PriceBreakdown(
        subtotal=float(raw.get("subtotal", raw.get("priceForOneSquareKm", 0))),
        processing_fee=float(raw.get("processingFee", raw.get("processing_fee", 0))),
        total=float(raw.get("total", raw.get("customerItemCost", 0))),
        currency=raw.get("currency", "USD"),
    )


def _map_order_status(api_status: str) -> OrderStatus:
    """Map a SkyFi DeliveryStatus to our OrderStatus enum."""
    status_map: dict[str, str] = {
        "CREATED": "pending",
        "STARTED": "processing",
        "PROVIDER_PENDING": "processing",
        "PROVIDER_COMPLETE": "processing",
        "PROCESSING_PENDING": "processing",
        "PROCESSING_COMPLETE": "processing",
        "DELIVERY_PENDING": "processing",
        "DELIVERY_COMPLETED": "delivered",
        "PAYMENT_FAILED": "failed",
        "PLATFORM_FAILED": "failed",
        "PROVIDER_FAILED": "failed",
        "PROCESSING_FAILED": "failed",
        "DELIVERY_FAILED": "failed",
        "INTERNAL_IMAGE_PROCESSING_PENDING": "processing",
    }
    mapped = status_map.get(api_status, api_status.lower())
    try:
        return OrderStatus(mapped)
    except ValueError:
        return OrderStatus.PROCESSING


# --------------------------------------------------------------------- #
# Order placement
# --------------------------------------------------------------------- #


async def place_archive_order(
    client: SkyFiClient,
    input: PlaceArchiveOrderInput,
    api_key: str,
) -> PlaceOrderOutput:
    """Place an archive imagery order.

    If ``input.confirmed`` is False (the default), returns a price preview.
    The actual order is only placed when ``confirmed=True``.

    The real API requires ``aoi`` (WKT) which we obtain by fetching the
    archive's footprint.
    """
    # Step 1: Fetch archive details to get pricing and footprint
    archive = await client.get_archive(api_key, archive_id=input.archive_id)

    price = PriceBreakdown(
        subtotal=float(archive.get("priceForOneSquareKm", 0)),
        processing_fee=0.0,
        total=float(archive.get("priceFullScene", 0)),
        currency="USD",
    )

    # Step 2: If not confirmed, return preview only -- NEVER auto-confirm
    if not require_confirmation(input.confirmed):
        return build_archive_order_preview(
            archive_id=input.archive_id,
            price=price,
            delivery_options=input.delivery_options,
            extra_details={
                "estimated_delivery_time": f"{archive.get('deliveryTimeHours', 24)} hours",
                "provider": archive.get("provider"),
                "total_area_sqkm": archive.get("totalAreaSquareKm"),
            },
        )

    # Step 3: Confirmed -- execute the order
    footprint = archive.get("footprint", "")
    body: dict[str, Any] = {
        "aoi": footprint,
        "archiveId": input.archive_id,
    }
    if input.delivery_options is not None:
        # Map delivery options to API format
        body["deliveryDriver"] = "NONE"
    if input.webhook_url:
        body["webhookUrl"] = input.webhook_url

    order_raw = await client.place_archive_order(api_key, body=body)

    return build_order_confirmation(
        order_id=order_raw.get("orderId", order_raw.get("id", "unknown")),
        price=price,
        estimated_delivery=f"{archive.get('deliveryTimeHours', 24)} hours",
    )


async def place_tasking_order(
    client: SkyFiClient,
    input: PlaceTaskingOrderInput,
    api_key: str,
) -> PlaceOrderOutput:
    """Place a tasking order.

    The real API requires aoi, windowStart, windowEnd, productType, and
    resolution. Same confirmation pattern as archive orders.
    """
    # Build the AOI from the location
    if input.location.geometry is None:
        raise ValueError("A geometry is required for tasking orders.")
    aoi = geojson_to_wkt(input.location.geometry.model_dump())

    # Get pricing estimate first
    pricing_raw = await client.get_pricing(api_key, body={"aoi": aoi})
    price = _parse_price(pricing_raw)

    # Step 2: Preview if not confirmed
    if not require_confirmation(input.confirmed):
        return build_tasking_order_preview(
            quote_id=f"tasking-{input.product_type}-{input.resolution}",
            price=price,
            extra_details={
                "product_type": input.product_type,
                "resolution": input.resolution,
                "window_start": input.window_start.isoformat(),
                "window_end": input.window_end.isoformat(),
            },
        )

    # Step 3: Confirmed -- execute the order
    body: dict[str, Any] = {
        "aoi": aoi,
        "windowStart": input.window_start.isoformat(),
        "windowEnd": input.window_end.isoformat(),
        "productType": input.product_type,
        "resolution": input.resolution,
    }
    if input.webhook_url:
        body["webhookUrl"] = input.webhook_url
    order_raw = await client.place_tasking_order(api_key, body=body)

    return build_order_confirmation(
        order_id=order_raw.get("orderId", order_raw.get("id", "unknown")),
        price=price,
        estimated_delivery=order_raw.get("estimatedDelivery"),
    )


# --------------------------------------------------------------------- #
# Order queries
# --------------------------------------------------------------------- #


async def get_order_status(
    client: SkyFiClient,
    input: GetOrderStatusInput,
    api_key: str,
) -> OrderStatusOutput:
    """Retrieve the current status of an order."""
    raw = await client.get_order(api_key, order_id=input.order_id)

    price_raw = raw.get("price")
    if price_raw:
        price = _parse_price(price_raw)
    elif raw.get("customerItemCost") is not None:
        price = PriceBreakdown(
            subtotal=float(raw["customerItemCost"]),
            processing_fee=0.0,
            total=float(raw["customerItemCost"]),
            currency="USD",
        )
    else:
        price = None

    api_status = raw.get("status", raw.get("deliveryStatus", "CREATED"))

    return OrderStatusOutput(
        order_id=raw.get("orderId", raw.get("id", input.order_id)),
        status=_map_order_status(api_status),
        created_at=raw.get("createdAt") or raw.get("created_at") or None,
        updated_at=raw.get("updatedAt") or raw.get("lastModified") or raw.get("createdAt") or None,
        price=price,
        delivery_urls=raw.get("deliveryUrls", []),
        metadata={k: raw[k] for k in ("orderType", "provider", "label") if k in raw},
    )


async def list_orders(
    client: SkyFiClient,
    input: ListOrdersInput,
    api_key: str,
) -> ListOrdersOutput:
    """List orders with optional filters."""
    params: dict[str, Any] = {}
    if input.status is not None:
        params["orderType"] = input.status.value.upper()
    if input.page > 1:
        params["pageNumber"] = input.page - 1  # API uses 0-indexed pages

    raw = await client.list_orders(api_key, params=params or None)

    # Real API returns a list of orders (may be directly a list or under a key)
    order_list = raw if isinstance(raw, list) else raw.get("orders", raw.get("items", []))
    if isinstance(order_list, dict):
        order_list = [order_list]

    orders: list[OrderStatusOutput] = []
    for item in order_list:
        api_status = item.get("status", item.get("deliveryStatus", "CREATED"))
        price_raw = item.get("price")
        price = _parse_price(price_raw) if price_raw else None
        if price is None and item.get("customerItemCost") is not None:
            price = PriceBreakdown(
                subtotal=float(item["customerItemCost"]),
                processing_fee=0.0,
                total=float(item["customerItemCost"]),
                currency="USD",
            )
        orders.append(
            OrderStatusOutput(
                order_id=item.get("orderId", item.get("id", "")),
                status=_map_order_status(api_status),
                created_at=item.get("createdAt") or item.get("created_at") or None,
                updated_at=item.get("updatedAt") or item.get("lastModified") or None,
                price=price,
                delivery_urls=item.get("deliveryUrls", []),
                metadata={k: item[k] for k in ("orderType", "provider", "label") if k in item},
            )
        )

    pagination = PaginationInfo(
        has_more=raw.get("hasMore", False) if isinstance(raw, dict) else False,
        next_offset=raw.get("nextPage") if isinstance(raw, dict) else None,
        total_count=raw.get("totalCount") if isinstance(raw, dict) else len(orders),
    )

    return ListOrdersOutput(orders=orders, pagination=pagination)


async def get_order_images(
    client: SkyFiClient,
    input: GetOrderImagesInput,
    api_key: str,
) -> OrderImagesOutput:
    """Retrieve download links for delivered imagery.

    Uses GET /orders/{id}/image for image deliverables.
    """
    try:
        raw = await client.get_order_deliverable(
            api_key, order_id=input.order_id, deliverable_type="image"
        )
        images = raw.get("images", [raw] if raw else [])
    except ValueError:
        # If no image deliverable, try COG format
        try:
            raw = await client.get_order_deliverable(
                api_key, order_id=input.order_id, deliverable_type="cog"
            )
            images = raw.get("images", [raw] if raw else [])
        except ValueError:
            images = []

    return OrderImagesOutput(
        order_id=input.order_id,
        images=images,
    )
