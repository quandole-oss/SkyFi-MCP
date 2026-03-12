"""
Monitoring & Notification tools.

Provides AOI monitoring setup, monitor management, webhook status checks,
and notification retrieval.
"""

from __future__ import annotations

import logging
from typing import Any

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

from skyfi_mcp.client.skyfi import SkyFiClient

logger = logging.getLogger(__name__)


def _location_dict(loc: Any) -> dict[str, Any]:
    """Convert a LocationInput to a plain dict."""
    payload: dict[str, Any] = {}
    if loc.geometry is not None:
        payload["geometry"] = loc.geometry.model_dump()
    if loc.address is not None:
        payload["address"] = loc.address
    return payload


def _parse_monitor(raw: dict[str, Any]) -> MonitorInfo:
    """Parse a MonitorInfo from raw API JSON."""
    return MonitorInfo(
        monitor_id=raw["monitorId"],
        location=GeoJSONGeometry(**raw["location"]),
        resolution_min=raw.get("resolutionMin"),
        notification_url=raw.get("notificationUrl"),
        created_at=raw["createdAt"],
        status=raw.get("status", "active"),
    )


async def setup_aoi_monitoring(
    client: SkyFiClient,
    input: SetupAOIMonitoringInput,
    api_key: str,
) -> SetupMonitorOutput:
    """Create an AOI monitor for new imagery notifications."""
    location = _location_dict(input.location)

    raw = await client.setup_monitoring(
        api_key,
        location=location,
        resolution_min=input.resolution_min,
        notification_url=input.notification_url,
    )

    monitor = _parse_monitor(raw.get("monitor", raw))

    return SetupMonitorOutput(
        monitor=monitor,
        message=raw.get("message", f"Monitor {monitor.monitor_id} created successfully."),
    )


async def list_monitors(
    client: SkyFiClient,
    api_key: str,
) -> ListMonitorsOutput:
    """List all active AOI monitors."""
    raw = await client.list_monitors(api_key)

    monitors: list[MonitorInfo] = []
    for item in raw.get("monitors", []):
        monitors.append(_parse_monitor(item))

    return ListMonitorsOutput(monitors=monitors)


async def delete_monitor(
    client: SkyFiClient,
    input: DeleteMonitorInput,
    api_key: str,
) -> DeleteMonitorOutput:
    """Delete an AOI monitor."""
    raw = await client.delete_monitor(api_key, monitor_id=input.monitor_id)

    return DeleteMonitorOutput(
        monitor_id=input.monitor_id,
        deleted=raw.get("deleted", True),
        message=raw.get("message", f"Monitor {input.monitor_id} deleted."),
    )


async def get_webhook_status(
    client: SkyFiClient,
    input: GetWebhookStatusInput,
    api_key: str,
) -> WebhookStatusOutput:
    """Check the status of a webhook subscription."""
    raw = await client.get_webhook_status(
        api_key, subscription_id=input.subscription_id
    )

    return WebhookStatusOutput(
        subscription_id=input.subscription_id,
        status=raw.get("status", "unknown"),
        last_delivery_at=raw.get("lastDeliveryAt"),
        delivery_count=raw.get("deliveryCount", 0),
        failure_count=raw.get("failureCount", 0),
    )


async def check_notifications(
    client: SkyFiClient,
    api_key: str,
) -> CheckNotificationsOutput:
    """Retrieve unread notifications."""
    raw = await client.check_notifications(api_key)

    notifications: list[Notification] = []
    for item in raw.get("notifications", []):
        notifications.append(
            Notification(
                notification_id=item["notificationId"],
                type=item.get("type", "unknown"),
                monitor_id=item.get("monitorId"),
                payload=item.get("payload", {}),
                created_at=item["createdAt"],
            )
        )

    return CheckNotificationsOutput(
        notifications=notifications,
        unread_count=raw.get("unreadCount", len(notifications)),
    )
