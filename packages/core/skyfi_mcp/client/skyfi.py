"""
SkyFi Platform API client.

Async HTTP client for communicating with the SkyFi satellite imagery API.
All methods require the API key to be passed explicitly — it is never stored.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from skyfi_mcp.client.models import SkyFiAPIError

logger = logging.getLogger(__name__)

# Default request timeout in seconds
_DEFAULT_TIMEOUT = 60.0


class SkyFiClient:
    """Async client for the SkyFi Platform API.

    Parameters
    ----------
    base_url:
        Root URL of the SkyFi platform API (no trailing slash).
    timeout:
        HTTP request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str = "https://app.skyfi.com/platform-api",
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    def _headers(self, api_key: str) -> dict[str, str]:
        return {
            "X-Skyfi-Api-Key": api_key,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _scrub_sensitive(data: dict[str, Any], api_key: str) -> dict[str, Any]:
        """Remove the API key from error response data to prevent credential leaks.

        Recursively walks the dict and replaces any occurrence of the API key
        with a redacted placeholder.
        """
        if not api_key:
            return data

        def _scrub(obj: Any) -> Any:
            if isinstance(obj, str):
                return obj.replace(api_key, "[REDACTED]")
            if isinstance(obj, dict):
                return {k: _scrub(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_scrub(item) for item in obj]
            return obj

        return _scrub(data)  # type: ignore[no-any-return]

    async def _request(
        self,
        method: str,
        path: str,
        api_key: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send an HTTP request and return the parsed JSON response.

        Raises ``SkyFiAPIError`` (as a dict via ``ValueError``) on HTTP errors
        so the caller can build a structured error output.
        """
        url = f"{self._base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(
                    method,
                    url,
                    headers=self._headers(api_key),
                    json=json_body,
                    params=params,
                )
                response.raise_for_status()
                return response.json()  # type: ignore[no-any-return]
        except httpx.HTTPStatusError as exc:
            # Try to parse body; fall back to generic message
            try:
                body = exc.response.json()
            except Exception:
                body = {"raw": exc.response.text}
            # Scrub the API key from any error details to prevent leaks
            safe_body = self._scrub_sensitive(body, api_key)
            error = SkyFiAPIError(
                status_code=exc.response.status_code,
                error=safe_body.get("error", "http_error"),
                message=safe_body.get("message", f"HTTP {exc.response.status_code} error"),
                details={k: v for k, v in safe_body.items() if k not in ("error", "message")},
            )
            raise ValueError(error.model_dump_json()) from None
        except httpx.RequestError as exc:
            error = SkyFiAPIError(
                status_code=0,
                error="connection_error",
                message=f"Failed to connect to SkyFi API: {type(exc).__name__}",
            )
            raise ValueError(error.model_dump_json()) from None

    # --------------------------------------------------------------------- #
    # Archive Search
    # --------------------------------------------------------------------- #

    async def search_archive(
        self,
        api_key: str,
        *,
        location: dict[str, Any],
        date_range: dict[str, Any] | None = None,
        resolution_min: float | None = None,
        sensor_type: str | None = None,
        cloud_cover_max: float | None = None,
        open_data: bool | None = None,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """POST /api/archive/search — search the SkyFi archive catalogue."""
        body: dict[str, Any] = {"location": location}
        if date_range is not None:
            body["dateRange"] = date_range
        if resolution_min is not None:
            body["resolutionMin"] = resolution_min
        if sensor_type is not None:
            body["sensorType"] = sensor_type
        if cloud_cover_max is not None:
            body["cloudCoverMax"] = cloud_cover_max
        if open_data is not None:
            body["openData"] = open_data
        if page_token is not None:
            body["nextPage"] = page_token
        return await self._request("POST", "/api/archive/search", api_key, json_body=body)

    async def get_archive_details(
        self, api_key: str, *, archive_id: str
    ) -> dict[str, Any]:
        """GET /api/archive/{archive_id} — full metadata for one image."""
        return await self._request("GET", f"/api/archive/{archive_id}", api_key)

    async def get_providers(
        self,
        api_key: str,
        *,
        location: dict[str, Any] | None = None,
        sensor_type: str | None = None,
    ) -> dict[str, Any]:
        """GET /api/providers — list available imagery providers."""
        params: dict[str, Any] = {}
        if sensor_type is not None:
            params["sensorType"] = sensor_type
        # If a location filter was provided, send as query JSON
        if location is not None:
            import json

            params["location"] = json.dumps(location)
        return await self._request("GET", "/api/providers", api_key, params=params or None)

    # --------------------------------------------------------------------- #
    # Pricing & Feasibility
    # --------------------------------------------------------------------- #

    async def estimate_archive_price(
        self,
        api_key: str,
        *,
        archive_id: str,
        delivery_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /api/archive/estimate-price — price estimate for an archive image."""
        body: dict[str, Any] = {"archiveId": archive_id}
        if delivery_options is not None:
            body["deliveryOptions"] = delivery_options
        return await self._request(
            "POST", "/api/archive/estimate-price", api_key, json_body=body
        )

    async def get_tasking_quote(
        self,
        api_key: str,
        *,
        location: dict[str, Any],
        resolution: float,
        sensor_type: str | None = None,
        time_window: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /api/tasking/quote — get a quote for new imagery capture."""
        body: dict[str, Any] = {
            "location": location,
            "resolution": resolution,
        }
        if sensor_type is not None:
            body["sensorType"] = sensor_type
        if time_window is not None:
            body["timeWindow"] = time_window
        return await self._request("POST", "/api/tasking/quote", api_key, json_body=body)

    async def analyze_feasibility(
        self,
        api_key: str,
        *,
        location: dict[str, Any],
        time_window: dict[str, Any] | None = None,
        resolution: float | None = None,
    ) -> dict[str, Any]:
        """POST /api/tasking/feasibility — analyze capture feasibility."""
        body: dict[str, Any] = {"location": location}
        if time_window is not None:
            body["timeWindow"] = time_window
        if resolution is not None:
            body["resolution"] = resolution
        return await self._request(
            "POST", "/api/tasking/feasibility", api_key, json_body=body
        )

    async def compare_pricing(
        self,
        api_key: str,
        *,
        location: dict[str, Any],
        resolution_options: list[float],
    ) -> dict[str, Any]:
        """POST /api/pricing/compare — compare pricing across providers."""
        body: dict[str, Any] = {
            "location": location,
            "resolutionOptions": resolution_options,
        }
        return await self._request("POST", "/api/pricing/compare", api_key, json_body=body)

    # --------------------------------------------------------------------- #
    # Orders
    # --------------------------------------------------------------------- #

    async def place_archive_order(
        self,
        api_key: str,
        *,
        archive_id: str,
        delivery_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /api/orders/archive — place an archive imagery order."""
        body: dict[str, Any] = {"archiveId": archive_id}
        if delivery_options is not None:
            body["deliveryOptions"] = delivery_options
        return await self._request("POST", "/api/orders/archive", api_key, json_body=body)

    async def place_tasking_order(
        self,
        api_key: str,
        *,
        quote_id: str,
    ) -> dict[str, Any]:
        """POST /api/orders/tasking — place a tasking order from a quote."""
        body: dict[str, Any] = {"quoteId": quote_id}
        return await self._request("POST", "/api/orders/tasking", api_key, json_body=body)

    async def get_order_status(
        self, api_key: str, *, order_id: str
    ) -> dict[str, Any]:
        """GET /api/orders/{order_id} — retrieve order status."""
        return await self._request("GET", f"/api/orders/{order_id}", api_key)

    async def list_orders(
        self,
        api_key: str,
        *,
        status: str | None = None,
        date_range: dict[str, Any] | None = None,
        page: int = 1,
    ) -> dict[str, Any]:
        """GET /api/orders — list orders with optional filters."""
        params: dict[str, Any] = {"page": page}
        if status is not None:
            params["status"] = status
        if date_range is not None:
            params["startDate"] = date_range.get("start", "")
            params["endDate"] = date_range.get("end", "")
        return await self._request("GET", "/api/orders", api_key, params=params)

    async def get_order_images(
        self, api_key: str, *, order_id: str
    ) -> dict[str, Any]:
        """GET /api/orders/{order_id}/images — download links for delivered imagery."""
        return await self._request("GET", f"/api/orders/{order_id}/images", api_key)

    # --------------------------------------------------------------------- #
    # Monitoring & Notifications
    # --------------------------------------------------------------------- #

    async def setup_monitoring(
        self,
        api_key: str,
        *,
        location: dict[str, Any],
        resolution_min: float | None = None,
        notification_url: str | None = None,
    ) -> dict[str, Any]:
        """POST /api/monitoring — create an AOI monitor."""
        body: dict[str, Any] = {"location": location}
        if resolution_min is not None:
            body["resolutionMin"] = resolution_min
        if notification_url is not None:
            body["notificationUrl"] = notification_url
        return await self._request("POST", "/api/monitoring", api_key, json_body=body)

    async def list_monitors(self, api_key: str) -> dict[str, Any]:
        """GET /api/monitoring — list active AOI monitors."""
        return await self._request("GET", "/api/monitoring", api_key)

    async def delete_monitor(
        self, api_key: str, *, monitor_id: str
    ) -> dict[str, Any]:
        """DELETE /api/monitoring/{monitor_id} — remove a monitor."""
        return await self._request("DELETE", f"/api/monitoring/{monitor_id}", api_key)

    async def get_webhook_status(
        self, api_key: str, *, subscription_id: str
    ) -> dict[str, Any]:
        """GET /api/webhooks/{subscription_id}/status — webhook delivery status."""
        return await self._request(
            "GET", f"/api/webhooks/{subscription_id}/status", api_key
        )

    async def check_notifications(self, api_key: str) -> dict[str, Any]:
        """GET /api/notifications — unread notifications."""
        return await self._request("GET", "/api/notifications", api_key)
