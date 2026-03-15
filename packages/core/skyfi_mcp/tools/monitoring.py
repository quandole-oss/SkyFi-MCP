"""
Monitoring & Notification tools.

Provides AOI monitoring setup, monitor management, webhook status checks,
and notification retrieval.

Real API endpoints:
  POST   /notifications            -- create notification filter
  GET    /notifications            -- list notifications
  GET    /notifications/{id}       -- notification details
  DELETE /notifications/{id}       -- delete notification
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from interfaces import (
    CheckNotificationsOutput,
    DeleteMonitorInput,
    DeleteMonitorOutput,
    GeoJSONGeometry,
    GetWebhookStatusInput,
    ListMonitorsOutput,
    MonitorInfo,
    Notification,
    SetupAOIMonitoringInput,
    SetupMonitorOutput,
    WebhookStatusOutput,
)
from skyfi_mcp.client.wkt import geojson_to_wkt, wkt_to_geojson

if TYPE_CHECKING:
    from skyfi_mcp.client.skyfi import SkyFiClient

logger = logging.getLogger(__name__)


def _parse_notification_as_monitor(raw: dict[str, Any]) -> MonitorInfo:
    """Parse a notification object from the API into a MonitorInfo model."""
    # The API stores notifications with aoi as WKT; convert to GeoJSON
    aoi_wkt = raw.get("aoi", "")
    if aoi_wkt:
        geom = GeoJSONGeometry(**wkt_to_geojson(aoi_wkt))
    else:
        geom = GeoJSONGeometry(type="Polygon", coordinates=[])

    return MonitorInfo(
        monitor_id=str(raw.get("id", raw.get("notificationId", ""))),
        location=geom,
        resolution_min=raw.get("gsdMin"),
        notification_url=raw.get("webhookUrl"),
        created_at=raw.get("createdAt", raw.get("created_at", "")),
        status=raw.get("status", "active"),
    )


async def setup_aoi_monitoring(
    client: SkyFiClient,
    input: SetupAOIMonitoringInput,
    api_key: str,
) -> SetupMonitorOutput:
    """Create an AOI notification for new imagery.

    Uses POST /notifications which requires ``aoi`` (WKT) and
    ``webhookUrl``.
    """
    if input.location.geometry is None:
        raise ValueError("A geometry is required for monitoring setup.")

    aoi = geojson_to_wkt(input.location.geometry.model_dump())

    body: dict[str, Any] = {
        "aoi": aoi,
    }
    if input.notification_url:
        body["webhookUrl"] = input.notification_url
    if input.resolution_min is not None:
        body["gsdMin"] = int(input.resolution_min)

    raw = await client.create_notification(api_key, body=body)

    monitor = _parse_notification_as_monitor(raw)

    return SetupMonitorOutput(
        monitor=monitor,
        message=raw.get("message", f"Monitor {monitor.monitor_id} created successfully."),
    )


async def list_monitors(
    client: SkyFiClient,
    api_key: str,
) -> ListMonitorsOutput:
    """List all active notifications (monitors)."""
    raw = await client.list_notifications(api_key)

    # Response may be a list directly or under a key
    items = raw if isinstance(raw, list) else raw.get("notifications", raw.get("items", []))
    if isinstance(items, dict):
        items = [items]

    monitors: list[MonitorInfo] = []
    for item in items:
        monitors.append(_parse_notification_as_monitor(item))

    return ListMonitorsOutput(monitors=monitors)


async def delete_monitor(
    client: SkyFiClient,
    input: DeleteMonitorInput,
    api_key: str,
) -> DeleteMonitorOutput:
    """Delete an active notification (monitor)."""
    raw = await client.delete_notification(api_key, notification_id=input.monitor_id)

    return DeleteMonitorOutput(
        monitor_id=input.monitor_id,
        deleted=True,
        message=raw.get("message", f"Monitor {input.monitor_id} deleted."),
    )


async def get_webhook_status(
    client: SkyFiClient,
    input: GetWebhookStatusInput,
    api_key: str,
) -> WebhookStatusOutput:
    """Check the status of a notification (webhook subscription).

    Uses GET /notifications/{id} since there's no dedicated webhook
    status endpoint.
    """
    raw = await client.get_notification(api_key, notification_id=input.subscription_id)

    return WebhookStatusOutput(
        subscription_id=input.subscription_id,
        status=raw.get("status", "active"),
        last_delivery_at=raw.get("lastDeliveryAt"),
        delivery_count=raw.get("deliveryCount", 0),
        failure_count=raw.get("failureCount", 0),
    )


async def check_notifications(
    client: SkyFiClient,
    api_key: str,
) -> CheckNotificationsOutput:
    """Retrieve notifications (same as list_notifications)."""
    raw = await client.list_notifications(api_key)

    items = raw if isinstance(raw, list) else raw.get("notifications", raw.get("items", []))
    if isinstance(items, dict):
        items = [items]

    notifications: list[Notification] = []
    for item in items:
        notifications.append(
            Notification(
                notification_id=str(item.get("id", item.get("notificationId", ""))),
                type=item.get("type", "notification"),
                monitor_id=str(item.get("id", "")),
                payload=item,
                created_at=item.get("createdAt", item.get("created_at", "")),
            )
        )

    return CheckNotificationsOutput(
        notifications=notifications,
        unread_count=len(notifications),
    )
