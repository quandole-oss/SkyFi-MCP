"""
SkyFi Platform API client.

Async HTTP client for communicating with the SkyFi satellite imagery API.
All methods require the API key to be passed explicitly -- it is never stored.

Endpoint mapping (from https://app.skyfi.com/platform-api/openapi.json):
  POST   /archives                        - search catalog
  GET    /archives?page=...               - continue paging
  GET    /archives/{archive_id}           - archive details
  POST   /pricing                         - tasking pricing options
  POST   /feasibility                     - check feasibility
  GET    /feasibility/{feasibility_id}    - feasibility status
  POST   /order-archive                   - place archive order
  POST   /order-tasking                   - place tasking order
  GET    /orders                          - list orders
  GET    /orders/{order_id}               - order details
  GET    /orders/{order_id}/{type}        - download deliverable
  POST   /notifications                   - create notification
  GET    /notifications                   - list notifications
  GET    /notifications/{id}              - notification details
  DELETE /notifications/{id}              - delete notification
  GET    /auth/whoami                     - current user
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
    auth_header:
        Name of the header used to send the API key.  Use ``"X-Skyfi-Api-Key"``
        (the default) for the official header, or ``"Bearer"`` to send as
        ``Authorization: Bearer <key>``.
    """

    def __init__(
        self,
        base_url: str = "https://app.skyfi.com/platform-api",
        timeout: float = _DEFAULT_TIMEOUT,
        auth_header: str = "X-Skyfi-Api-Key",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._auth_header = auth_header

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    def _headers(self, api_key: str) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._auth_header == "Bearer":
            headers["Authorization"] = f"Bearer {api_key}"
        else:
            headers[self._auth_header] = api_key
        return headers

    @staticmethod
    def _scrub_sensitive(data: dict[str, Any], api_key: str) -> dict[str, Any]:
        """Remove the API key from error response data to prevent credential leaks."""
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
        """Send an HTTP request and return the parsed JSON response."""
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
                # Some endpoints (DELETE) may return empty bodies
                if response.status_code == 204 or not response.content:
                    return {}
                return response.json()  # type: ignore[no-any-return]
        except httpx.HTTPStatusError as exc:
            try:
                body = exc.response.json()
            except Exception:
                body = {"raw": exc.response.text}
            safe_body = self._scrub_sensitive(body, api_key)
            error = SkyFiAPIError(
                status_code=exc.response.status_code,
                error=safe_body.get("error", safe_body.get("detail", "http_error")),
                message=safe_body.get(
                    "message",
                    safe_body.get("detail", f"HTTP {exc.response.status_code} error"),
                ),
                details={
                    k: v
                    for k, v in safe_body.items()
                    if k not in ("error", "message", "detail")
                },
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

    async def search_archives(
        self,
        api_key: str,
        *,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /archives -- search the SkyFi archive catalogue.

        The ``body`` dict should contain at least ``aoi`` (WKT geometry string)
        and may include ``fromDate``, ``toDate``, ``maxCloudCoveragePercent``,
        ``resolutions``, ``productTypes``, ``providers``, ``openData``,
        ``pageSize``, etc.
        """
        return await self._request("POST", "/archives", api_key, json_body=body)

    async def search_archives_page(
        self,
        api_key: str,
        *,
        page_token: str,
    ) -> dict[str, Any]:
        """GET /archives?page=... -- continue paging through results."""
        return await self._request("GET", "/archives", api_key, params={"page": page_token})

    async def get_archive(
        self,
        api_key: str,
        *,
        archive_id: str,
    ) -> dict[str, Any]:
        """GET /archives/{archive_id} -- full metadata for one archive image."""
        return await self._request("GET", f"/archives/{archive_id}", api_key)

    # --------------------------------------------------------------------- #
    # Pricing & Feasibility
    # --------------------------------------------------------------------- #

    async def get_pricing(
        self,
        api_key: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST /pricing -- get pricing options for tasking orders."""
        return await self._request("POST", "/pricing", api_key, json_body=body or {})

    async def create_feasibility(
        self,
        api_key: str,
        *,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /feasibility -- check capture feasibility for an AOI."""
        return await self._request("POST", "/feasibility", api_key, json_body=body)

    async def get_feasibility(
        self,
        api_key: str,
        *,
        feasibility_id: str,
    ) -> dict[str, Any]:
        """GET /feasibility/{feasibility_id} -- poll feasibility status."""
        return await self._request("GET", f"/feasibility/{feasibility_id}", api_key)

    # --------------------------------------------------------------------- #
    # Orders
    # --------------------------------------------------------------------- #

    async def place_archive_order(
        self,
        api_key: str,
        *,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /order-archive -- place an archive imagery order.

        Required body keys: ``aoi`` (WKT), ``archiveId``.
        Optional: ``deliveryDriver``, ``deliveryParams``, ``label``,
        ``orderLabel``, ``metadata``, ``webhookUrl``.
        """
        return await self._request("POST", "/order-archive", api_key, json_body=body)

    async def place_tasking_order(
        self,
        api_key: str,
        *,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /order-tasking -- place a tasking order.

        Required body keys: ``aoi`` (WKT), ``windowStart``, ``windowEnd``,
        ``productType``, ``resolution``.
        """
        return await self._request("POST", "/order-tasking", api_key, json_body=body)

    async def list_orders(
        self,
        api_key: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET /orders -- list customer orders."""
        return await self._request("GET", "/orders", api_key, params=params)

    async def get_order(
        self,
        api_key: str,
        *,
        order_id: str,
    ) -> dict[str, Any]:
        """GET /orders/{order_id} -- order details with status history."""
        return await self._request("GET", f"/orders/{order_id}", api_key)

    async def get_order_deliverable(
        self,
        api_key: str,
        *,
        order_id: str,
        deliverable_type: str = "image",
    ) -> dict[str, Any]:
        """GET /orders/{order_id}/{deliverable_type} -- download deliverable."""
        return await self._request(
            "GET", f"/orders/{order_id}/{deliverable_type}", api_key
        )

    # --------------------------------------------------------------------- #
    # Notifications (Monitoring)
    # --------------------------------------------------------------------- #

    async def create_notification(
        self,
        api_key: str,
        *,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /notifications -- create an AOI notification filter.

        Required body keys: ``aoi`` (WKT), ``webhookUrl``.
        Optional: ``gsdMin``, ``gsdMax``, ``productType``.
        """
        return await self._request("POST", "/notifications", api_key, json_body=body)

    async def list_notifications(
        self,
        api_key: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET /notifications -- list active notifications."""
        return await self._request("GET", "/notifications", api_key, params=params)

    async def get_notification(
        self,
        api_key: str,
        *,
        notification_id: str,
    ) -> dict[str, Any]:
        """GET /notifications/{id} -- notification details with history."""
        return await self._request(
            "GET", f"/notifications/{notification_id}", api_key
        )

    async def delete_notification(
        self,
        api_key: str,
        *,
        notification_id: str,
    ) -> dict[str, Any]:
        """DELETE /notifications/{id} -- delete an active notification."""
        return await self._request(
            "DELETE", f"/notifications/{notification_id}", api_key
        )

    # --------------------------------------------------------------------- #
    # Auth
    # --------------------------------------------------------------------- #

    async def whoami(self, api_key: str) -> dict[str, Any]:
        """GET /auth/whoami -- get the current user."""
        return await self._request("GET", "/auth/whoami", api_key)
