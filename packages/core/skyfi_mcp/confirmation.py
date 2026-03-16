"""
Human confirmation logic for order placement.

Provides helper functions to build ``OrderConfirmationPreview`` responses and
to validate that the ``confirmed`` flag is set before executing an order.
Orders must NEVER be auto-confirmed.
"""

from __future__ import annotations

from typing import Any

from interfaces import (
    DeliveryOptions,
    OrderConfirmation,
    OrderConfirmationPreview,
    OrderStatus,
    PlaceOrderOutput,
    PriceBreakdown,
)


def build_archive_order_preview(
    *,
    archive_id: str,
    price: PriceBreakdown,
    delivery_options: DeliveryOptions | None = None,
    extra_details: dict[str, Any] | None = None,
) -> PlaceOrderOutput:
    """Build a preview response for an unconfirmed archive order.

    The caller should return this to the user so they can review the price
    and details before re-calling with ``confirmed=True``.
    """
    details: dict[str, Any] = {"archive_id": archive_id}
    if delivery_options is not None:
        details["delivery_options"] = delivery_options.model_dump()
    if extra_details:
        details.update(extra_details)

    preview = OrderConfirmationPreview(
        order_type="archive",
        price=price,
        details=details,
        message=(
            f"Archive order for image {archive_id}. "
            f"Total cost: ${price.total:.2f} {price.currency}. "
            "Please confirm by calling again with confirmed=true."
        ),
    )
    return PlaceOrderOutput(preview=preview, confirmation=None)


def build_tasking_order_preview(
    *,
    quote_id: str,
    price: PriceBreakdown,
    extra_details: dict[str, Any] | None = None,
) -> PlaceOrderOutput:
    """Build a preview response for an unconfirmed tasking order."""
    details: dict[str, Any] = {"quote_id": quote_id}
    if extra_details:
        details.update(extra_details)

    preview = OrderConfirmationPreview(
        order_type="tasking",
        price=price,
        details=details,
        message=(
            f"Tasking order from quote {quote_id}. "
            f"Total cost: ${price.total:.2f} {price.currency}. "
            "Please confirm by calling again with confirmed=true."
        ),
    )
    return PlaceOrderOutput(preview=preview, confirmation=None)


def build_order_confirmation(
    *,
    order_id: str,
    price: PriceBreakdown,
    estimated_delivery: str | None = None,
) -> PlaceOrderOutput:
    """Build a confirmation response after a successful order placement."""
    order_url = f"https://app.skyfi.com/orders/{order_id}"
    confirmation = OrderConfirmation(
        order_id=order_id,
        order_url=order_url,
        status=OrderStatus.CONFIRMED,
        price=price,
        estimated_delivery=estimated_delivery,
        message=f"Order {order_id} placed successfully. View it at {order_url}",
    )
    return PlaceOrderOutput(preview=None, confirmation=confirmation)


def require_confirmation(confirmed: bool) -> bool:
    """Return True if the order should proceed, False if a preview is needed.

    This is intentionally simple — the key guarantee is that we never
    auto-confirm. Callers check:

        if not require_confirmation(input.confirmed):
            return build_*_preview(...)
    """
    return confirmed is True
