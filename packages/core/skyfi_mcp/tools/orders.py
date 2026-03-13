"""
Order Management tools.

Handles archive and tasking order placement with mandatory human confirmation,
order status queries, order listing, and delivered-image retrieval.

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
        subtotal=float(raw.get("subtotal", 0)),
        processing_fee=float(raw.get("processingFee", raw.get("processing_fee", 0))),
        total=float(raw.get("total", 0)),
        currency=raw.get("currency", "USD"),
    )


# --------------------------------------------------------------------- #
# Order placement
# --------------------------------------------------------------------- #


async def place_archive_order(
    client: SkyFiClient,
    input: PlaceArchiveOrderInput,
    api_key: str,
) -> PlaceOrderOutput:
    """Place an archive imagery order.

    If ``input.confirmed`` is False (the default), returns a price preview
    so the user can review before committing. The actual order is only
    placed when ``confirmed=True``.
    """
    # Step 1: Always fetch a price estimate first
    delivery_opts: dict[str, Any] | None = None
    if input.delivery_options is not None:
        delivery_opts = input.delivery_options.model_dump()

    estimate_raw = await client.estimate_archive_price(
        api_key,
        archive_id=input.archive_id,
        delivery_options=delivery_opts,
    )
    price = _parse_price(estimate_raw.get("price", estimate_raw))

    # Step 2: If not confirmed, return preview only — NEVER auto-confirm
    if not require_confirmation(input.confirmed):
        return build_archive_order_preview(
            archive_id=input.archive_id,
            price=price,
            delivery_options=input.delivery_options,
            extra_details={
                "estimated_delivery_time": estimate_raw.get("estimatedDeliveryTime"),
            },
        )

    # Step 3: Confirmed — execute the order
    order_raw = await client.place_archive_order(
        api_key,
        archive_id=input.archive_id,
        delivery_options=delivery_opts,
    )

    return build_order_confirmation(
        order_id=order_raw["orderId"],
        price=price,
        estimated_delivery=order_raw.get("estimatedDelivery"),
    )


async def place_tasking_order(
    client: SkyFiClient,
    input: PlaceTaskingOrderInput,
    api_key: str,
) -> PlaceOrderOutput:
    """Place a tasking order from an existing quote.

    Same confirmation pattern as archive orders — preview first, execute
    only when ``confirmed=True``.
    """
    # Step 1: Fetch quote details to show price
    quote_raw = await client.get_tasking_quote(
        api_key,
        # We re-fetch quote info via the order preview endpoint.
        # Since we only have the quote_id at this point, we call the
        # tasking order endpoint which returns price info.
        location={"quoteId": input.quote_id},
        resolution=0,  # placeholder — server uses quote_id
    )
    price = _parse_price(quote_raw.get("price", {}))

    # Step 2: Preview if not confirmed
    if not require_confirmation(input.confirmed):
        return build_tasking_order_preview(
            quote_id=input.quote_id,
            price=price,
            extra_details={
                "provider": quote_raw.get("provider"),
                "feasibility_score": quote_raw.get("feasibilityScore"),
                "expires_at": quote_raw.get("expiresAt"),
            },
        )

    # Step 3: Confirmed — execute the order
    order_raw = await client.place_tasking_order(
        api_key,
        quote_id=input.quote_id,
    )

    return build_order_confirmation(
        order_id=order_raw["orderId"],
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
    raw = await client.get_order_status(api_key, order_id=input.order_id)
    price_raw = raw.get("price")
    price = _parse_price(price_raw) if price_raw else None
    return OrderStatusOutput(
        order_id=raw["orderId"],
        status=OrderStatus(raw.get("status", "pending")),
        created_at=raw["createdAt"],
        updated_at=raw["updatedAt"],
        price=price,
        delivery_urls=raw.get("deliveryUrls", []),
        metadata=raw.get("metadata", {}),
    )


async def list_orders(
    client: SkyFiClient,
    input: ListOrdersInput,
    api_key: str,
) -> ListOrdersOutput:
    """List orders with optional status and date filters."""
    date_range: dict[str, Any] | None = None
    if input.date_range is not None:
        date_range = {
            "start": input.date_range.start.isoformat(),
            "end": input.date_range.end.isoformat(),
        }

    raw = await client.list_orders(
        api_key,
        status=input.status.value if input.status else None,
        date_range=date_range,
        page=input.page,
    )

    orders: list[OrderStatusOutput] = []
    for item in raw.get("orders", []):
        price_raw = item.get("price")
        price = _parse_price(price_raw) if price_raw else None
        orders.append(
            OrderStatusOutput(
                order_id=item["orderId"],
                status=OrderStatus(item.get("status", "pending")),
                created_at=item["createdAt"],
                updated_at=item["updatedAt"],
                price=price,
                delivery_urls=item.get("deliveryUrls", []),
                metadata=item.get("metadata", {}),
            )
        )

    pagination = PaginationInfo(
        has_more=raw.get("hasMore", False),
        next_offset=raw.get("nextPage"),
        total_count=raw.get("totalCount"),
    )

    return ListOrdersOutput(orders=orders, pagination=pagination)


async def get_order_images(
    client: SkyFiClient,
    input: GetOrderImagesInput,
    api_key: str,
) -> OrderImagesOutput:
    """Retrieve download links for delivered imagery."""
    raw = await client.get_order_images(api_key, order_id=input.order_id)
    return OrderImagesOutput(
        order_id=input.order_id,
        images=raw.get("images", []),
    )
