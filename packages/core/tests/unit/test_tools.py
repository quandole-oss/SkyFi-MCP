"""
Unit tests for SkyFi MCP tool functions.

Uses ``respx`` to mock httpx requests so no real HTTP calls are made.
Covers:
- Every tool with valid input
- Error cases (API errors, invalid input)
- Confirmation flow (preview vs. execute)
- Search pagination (nextPage handling)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest
import respx

from interfaces import (
    AnalyzeFeasibilityInput,
    ComparePricingInput,
    DateRange,
    DeleteMonitorInput,
    DeliveryFormat,
    DeliveryOptions,
    EstimateArchivePriceInput,
    ExploreProvidersInput,
    GeoJSONGeometry,
    GetArchiveDetailsInput,
    GetOrderImagesInput,
    GetOrderStatusInput,
    GetTaskingQuoteInput,
    GetWebhookStatusInput,
    ListOrdersInput,
    LocationInput,
    PlaceArchiveOrderInput,
    PlaceTaskingOrderInput,
    SearchArchiveInput,
    SensorType,
    SetupAOIMonitoringInput,
)

from skyfi_mcp.client.skyfi import SkyFiClient
from skyfi_mcp.tools import monitoring, orders, pricing, search

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE_URL = "https://test.skyfi.local/platform-api"
API_KEY = "test-api-key-do-not-use"

NOW_ISO = "2025-06-01T12:00:00Z"
NOW_DT = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def client() -> SkyFiClient:
    return SkyFiClient(base_url=BASE_URL)


@pytest.fixture()
def sample_location() -> LocationInput:
    return LocationInput(
        geometry=GeoJSONGeometry(
            type="Polygon",
            coordinates=[
                [
                    [-122.4, 37.7],
                    [-122.4, 37.8],
                    [-122.3, 37.8],
                    [-122.3, 37.7],
                    [-122.4, 37.7],
                ]
            ],
        )
    )


def _geom_dict() -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [-122.4, 37.7],
                [-122.4, 37.8],
                [-122.3, 37.8],
                [-122.3, 37.7],
                [-122.4, 37.7],
            ]
        ],
    }


# ---------------------------------------------------------------------------
# Search & Discovery
# ---------------------------------------------------------------------------


class TestSearchArchive:
    @respx.mock
    @pytest.mark.asyncio
    async def test_basic_search(self, client: SkyFiClient, sample_location: LocationInput):
        respx.post(f"{BASE_URL}/api/archive/search").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "archiveId": "img-001",
                            "provider": "Maxar",
                            "sensorType": "optical",
                            "resolution": 0.5,
                            "captureDate": NOW_ISO,
                            "cloudCover": 10.0,
                            "geometry": _geom_dict(),
                            "thumbnailUrl": "https://example.com/thumb.png",
                            "openData": False,
                        }
                    ],
                    "totalCount": 1,
                    "nextPage": None,
                },
            )
        )

        inp = SearchArchiveInput(location=sample_location)
        result = await search.search_archive(client, inp, API_KEY)

        assert len(result.results) == 1
        assert result.results[0].archive_id == "img-001"
        assert result.results[0].provider == "Maxar"
        assert result.results[0].resolution == 0.5
        assert result.pagination.has_more is False
        assert result.pagination.total_count == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_pagination(self, client: SkyFiClient, sample_location: LocationInput):
        """Verify nextPage handling: first page has more, second does not."""
        respx.post(f"{BASE_URL}/api/archive/search").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "archiveId": "img-page1",
                            "provider": "Planet",
                            "sensorType": "optical",
                            "resolution": 3.0,
                            "captureDate": NOW_ISO,
                            "geometry": _geom_dict(),
                        }
                    ],
                    "totalCount": 50,
                    "nextPage": "cursor-abc123",
                },
            )
        )

        inp = SearchArchiveInput(location=sample_location)
        result = await search.search_archive(client, inp, API_KEY)

        assert result.pagination.has_more is True
        assert result.pagination.next_offset == "cursor-abc123"
        assert result.pagination.total_count == 50

        # Simulate second page
        respx.post(f"{BASE_URL}/api/archive/search").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "archiveId": "img-page2",
                            "provider": "Planet",
                            "sensorType": "optical",
                            "resolution": 3.0,
                            "captureDate": NOW_ISO,
                            "geometry": _geom_dict(),
                        }
                    ],
                    "totalCount": 50,
                    "nextPage": None,
                },
            )
        )

        inp2 = SearchArchiveInput(location=sample_location, page_token="cursor-abc123")
        result2 = await search.search_archive(client, inp2, API_KEY)
        assert result2.pagination.has_more is False
        assert result2.results[0].archive_id == "img-page2"

    @respx.mock
    @pytest.mark.asyncio
    async def test_api_error(self, client: SkyFiClient, sample_location: LocationInput):
        respx.post(f"{BASE_URL}/api/archive/search").mock(
            return_value=httpx.Response(
                403,
                json={"error": "forbidden", "message": "Invalid API key"},
            )
        )

        inp = SearchArchiveInput(location=sample_location)
        with pytest.raises(ValueError, match="forbidden"):
            await search.search_archive(client, inp, API_KEY)


class TestGetArchiveDetails:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient):
        respx.get(f"{BASE_URL}/api/archive/img-001").mock(
            return_value=httpx.Response(
                200,
                json={
                    "archiveId": "img-001",
                    "provider": "Maxar",
                    "sensorType": "multispectral",
                    "resolution": 0.3,
                    "captureDate": NOW_ISO,
                    "cloudCover": 5.0,
                    "geometry": _geom_dict(),
                    "bands": ["R", "G", "B", "NIR"],
                    "fileSizeMb": 256.5,
                    "license": "commercial",
                    "metadata": {"satellite": "WorldView-3"},
                },
            )
        )

        inp = GetArchiveDetailsInput(archive_id="img-001")
        result = await search.get_archive_details(client, inp, API_KEY)

        assert result.archive_id == "img-001"
        assert result.sensor_type == SensorType.MULTISPECTRAL
        assert result.bands == ["R", "G", "B", "NIR"]
        assert result.file_size_mb == 256.5


class TestExploreProviders:
    @respx.mock
    @pytest.mark.asyncio
    async def test_list_all(self, client: SkyFiClient):
        respx.get(f"{BASE_URL}/api/providers").mock(
            return_value=httpx.Response(
                200,
                json={
                    "providers": [
                        {
                            "providerId": "maxar",
                            "name": "Maxar Technologies",
                            "sensorTypes": ["optical", "multispectral"],
                            "resolutionRange": [0.3, 1.0],
                            "coverageDescription": "Global",
                        },
                        {
                            "providerId": "planet",
                            "name": "Planet Labs",
                            "sensorTypes": ["optical"],
                            "resolutionRange": [3.0, 5.0],
                            "coverageDescription": "Daily global",
                        },
                    ]
                },
            )
        )

        inp = ExploreProvidersInput()
        result = await search.explore_providers(client, inp, API_KEY)

        assert len(result.providers) == 2
        assert result.providers[0].provider_id == "maxar"
        assert SensorType.MULTISPECTRAL in result.providers[0].sensor_types


# ---------------------------------------------------------------------------
# Pricing & Feasibility
# ---------------------------------------------------------------------------


class TestEstimateArchivePrice:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient):
        respx.post(f"{BASE_URL}/api/archive/estimate-price").mock(
            return_value=httpx.Response(
                200,
                json={
                    "price": {
                        "subtotal": 100.0,
                        "processingFee": 10.0,
                        "total": 110.0,
                        "currency": "USD",
                    },
                    "estimatedDeliveryTime": "2-4 hours",
                },
            )
        )

        inp = EstimateArchivePriceInput(
            archive_id="img-001",
            delivery_options=DeliveryOptions(format=DeliveryFormat.COG),
        )
        result = await pricing.estimate_archive_price(client, inp, API_KEY)

        assert result.archive_id == "img-001"
        assert result.price.total == 110.0
        assert result.estimated_delivery_time == "2-4 hours"


class TestGetTaskingQuote:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient, sample_location: LocationInput):
        respx.post(f"{BASE_URL}/api/tasking/quote").mock(
            return_value=httpx.Response(
                200,
                json={
                    "quoteId": "quote-789",
                    "price": {
                        "subtotal": 500.0,
                        "processingFee": 50.0,
                        "total": 550.0,
                    },
                    "feasibilityScore": 0.85,
                    "provider": "Maxar",
                    "resolution": 0.5,
                    "expiresAt": "2025-06-10T00:00:00Z",
                },
            )
        )

        inp = GetTaskingQuoteInput(
            location=sample_location,
            resolution=0.5,
            sensor_type=SensorType.OPTICAL,
        )
        result = await pricing.get_tasking_quote(client, inp, API_KEY)

        assert result.quote_id == "quote-789"
        assert result.feasibility_score == 0.85
        assert result.price.total == 550.0


class TestAnalyzeFeasibility:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient, sample_location: LocationInput):
        respx.post(f"{BASE_URL}/api/tasking/feasibility").mock(
            return_value=httpx.Response(
                200,
                json={
                    "feasibilityScore": 0.72,
                    "cloudForecast": "Partly cloudy",
                    "satellitePasses": [
                        {"satellite": "WV3", "time": NOW_ISO}
                    ],
                    "captureWindows": [
                        {"start": NOW_ISO, "end": "2025-06-05T12:00:00Z"}
                    ],
                    "recommendations": "Consider a wider time window.",
                },
            )
        )

        inp = AnalyzeFeasibilityInput(location=sample_location)
        result = await pricing.analyze_feasibility(client, inp, API_KEY)

        assert result.feasibility_score == 0.72
        assert result.cloud_forecast == "Partly cloudy"
        assert len(result.capture_windows) == 1


class TestComparePricing:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient, sample_location: LocationInput):
        respx.post(f"{BASE_URL}/api/pricing/compare").mock(
            return_value=httpx.Response(
                200,
                json={
                    "comparisons": [
                        {
                            "provider": "Maxar",
                            "resolution": 0.5,
                            "price": {"subtotal": 100, "total": 110},
                            "sensorType": "optical",
                        },
                        {
                            "provider": "Planet",
                            "resolution": 3.0,
                            "price": {"subtotal": 30, "total": 33},
                            "sensorType": "optical",
                        },
                    ],
                    "recommended": {
                        "provider": "Planet",
                        "resolution": 3.0,
                        "price": {"subtotal": 30, "total": 33},
                        "sensorType": "optical",
                    },
                },
            )
        )

        inp = ComparePricingInput(
            location=sample_location, resolution_options=[0.5, 3.0]
        )
        result = await pricing.compare_pricing(client, inp, API_KEY)

        assert len(result.comparisons) == 2
        assert result.recommended is not None
        assert result.recommended.provider == "Planet"


# ---------------------------------------------------------------------------
# Order Management — Confirmation flow
# ---------------------------------------------------------------------------


class TestPlaceArchiveOrder:
    @respx.mock
    @pytest.mark.asyncio
    async def test_preview_when_not_confirmed(self, client: SkyFiClient):
        """confirmed=False should return a preview, NOT place the order."""
        respx.post(f"{BASE_URL}/api/archive/estimate-price").mock(
            return_value=httpx.Response(
                200,
                json={
                    "price": {
                        "subtotal": 100.0,
                        "processingFee": 10.0,
                        "total": 110.0,
                    },
                    "estimatedDeliveryTime": "2-4 hours",
                },
            )
        )

        inp = PlaceArchiveOrderInput(archive_id="img-001", confirmed=False)
        result = await orders.place_archive_order(client, inp, API_KEY)

        # Must be a preview, not a confirmation
        assert result.preview is not None
        assert result.confirmation is None
        assert result.preview.order_type == "archive"
        assert result.preview.price.total == 110.0
        assert "confirm" in result.preview.message.lower()

    @respx.mock
    @pytest.mark.asyncio
    async def test_preview_default_confirmed(self, client: SkyFiClient):
        """Default (no confirmed kwarg) should also return preview."""
        respx.post(f"{BASE_URL}/api/archive/estimate-price").mock(
            return_value=httpx.Response(
                200,
                json={"price": {"subtotal": 50, "total": 55}},
            )
        )

        inp = PlaceArchiveOrderInput(archive_id="img-002")
        result = await orders.place_archive_order(client, inp, API_KEY)

        assert result.preview is not None
        assert result.confirmation is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_when_confirmed(self, client: SkyFiClient):
        """confirmed=True should actually place the order."""
        respx.post(f"{BASE_URL}/api/archive/estimate-price").mock(
            return_value=httpx.Response(
                200,
                json={
                    "price": {"subtotal": 100, "processingFee": 10, "total": 110},
                },
            )
        )
        respx.post(f"{BASE_URL}/api/orders/archive").mock(
            return_value=httpx.Response(
                200,
                json={
                    "orderId": "ord-001",
                    "estimatedDelivery": "2-4 hours",
                },
            )
        )

        inp = PlaceArchiveOrderInput(archive_id="img-001", confirmed=True)
        result = await orders.place_archive_order(client, inp, API_KEY)

        assert result.confirmation is not None
        assert result.preview is None
        assert result.confirmation.order_id == "ord-001"
        assert result.confirmation.price.total == 110.0


class TestPlaceTaskingOrder:
    @respx.mock
    @pytest.mark.asyncio
    async def test_preview_when_not_confirmed(self, client: SkyFiClient):
        respx.post(f"{BASE_URL}/api/tasking/quote").mock(
            return_value=httpx.Response(
                200,
                json={
                    "quoteId": "quote-789",
                    "price": {"subtotal": 500, "total": 550},
                    "feasibilityScore": 0.85,
                },
            )
        )

        inp = PlaceTaskingOrderInput(quote_id="quote-789", confirmed=False)
        result = await orders.place_tasking_order(client, inp, API_KEY)

        assert result.preview is not None
        assert result.confirmation is None
        assert result.preview.order_type == "tasking"

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_when_confirmed(self, client: SkyFiClient):
        respx.post(f"{BASE_URL}/api/tasking/quote").mock(
            return_value=httpx.Response(
                200,
                json={
                    "quoteId": "quote-789",
                    "price": {"subtotal": 500, "total": 550},
                },
            )
        )
        respx.post(f"{BASE_URL}/api/orders/tasking").mock(
            return_value=httpx.Response(
                200,
                json={
                    "orderId": "ord-task-001",
                    "estimatedDelivery": "3-5 days",
                },
            )
        )

        inp = PlaceTaskingOrderInput(quote_id="quote-789", confirmed=True)
        result = await orders.place_tasking_order(client, inp, API_KEY)

        assert result.confirmation is not None
        assert result.confirmation.order_id == "ord-task-001"


class TestGetOrderStatus:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient):
        respx.get(f"{BASE_URL}/api/orders/ord-001").mock(
            return_value=httpx.Response(
                200,
                json={
                    "orderId": "ord-001",
                    "status": "processing",
                    "createdAt": NOW_ISO,
                    "updatedAt": NOW_ISO,
                    "price": {"subtotal": 100, "total": 110},
                },
            )
        )

        inp = GetOrderStatusInput(order_id="ord-001")
        result = await orders.get_order_status(client, inp, API_KEY)

        assert result.order_id == "ord-001"
        assert result.status.value == "processing"


class TestListOrders:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient):
        respx.get(f"{BASE_URL}/api/orders").mock(
            return_value=httpx.Response(
                200,
                json={
                    "orders": [
                        {
                            "orderId": "ord-001",
                            "status": "delivered",
                            "createdAt": NOW_ISO,
                            "updatedAt": NOW_ISO,
                        }
                    ],
                    "hasMore": False,
                    "totalCount": 1,
                },
            )
        )

        inp = ListOrdersInput()
        result = await orders.list_orders(client, inp, API_KEY)

        assert len(result.orders) == 1
        assert result.pagination.has_more is False


class TestGetOrderImages:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient):
        respx.get(f"{BASE_URL}/api/orders/ord-001/images").mock(
            return_value=httpx.Response(
                200,
                json={
                    "images": [
                        {
                            "url": "https://cdn.skyfi.com/img.tif",
                            "format": "geotiff",
                            "size_mb": 128.0,
                        }
                    ]
                },
            )
        )

        inp = GetOrderImagesInput(order_id="ord-001")
        result = await orders.get_order_images(client, inp, API_KEY)

        assert result.order_id == "ord-001"
        assert len(result.images) == 1
        assert result.images[0]["format"] == "geotiff"


# ---------------------------------------------------------------------------
# Monitoring & Notifications
# ---------------------------------------------------------------------------


class TestSetupAOIMonitoring:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient, sample_location: LocationInput):
        respx.post(f"{BASE_URL}/api/monitoring").mock(
            return_value=httpx.Response(
                200,
                json={
                    "monitor": {
                        "monitorId": "mon-001",
                        "location": _geom_dict(),
                        "resolutionMin": 1.0,
                        "createdAt": NOW_ISO,
                        "status": "active",
                    },
                    "message": "Monitor created.",
                },
            )
        )

        inp = SetupAOIMonitoringInput(location=sample_location, resolution_min=1.0)
        result = await monitoring.setup_aoi_monitoring(client, inp, API_KEY)

        assert result.monitor.monitor_id == "mon-001"
        assert result.monitor.status == "active"


class TestListMonitors:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient):
        respx.get(f"{BASE_URL}/api/monitoring").mock(
            return_value=httpx.Response(
                200,
                json={
                    "monitors": [
                        {
                            "monitorId": "mon-001",
                            "location": _geom_dict(),
                            "createdAt": NOW_ISO,
                            "status": "active",
                        }
                    ]
                },
            )
        )

        result = await monitoring.list_monitors(client, API_KEY)
        assert len(result.monitors) == 1


class TestDeleteMonitor:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient):
        respx.delete(f"{BASE_URL}/api/monitoring/mon-001").mock(
            return_value=httpx.Response(
                200,
                json={"deleted": True, "message": "Monitor mon-001 deleted."},
            )
        )

        inp = DeleteMonitorInput(monitor_id="mon-001")
        result = await monitoring.delete_monitor(client, inp, API_KEY)

        assert result.deleted is True
        assert result.monitor_id == "mon-001"


class TestGetWebhookStatus:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient):
        respx.get(f"{BASE_URL}/api/webhooks/sub-001/status").mock(
            return_value=httpx.Response(
                200,
                json={
                    "status": "active",
                    "lastDeliveryAt": NOW_ISO,
                    "deliveryCount": 42,
                    "failureCount": 1,
                },
            )
        )

        inp = GetWebhookStatusInput(subscription_id="sub-001")
        result = await monitoring.get_webhook_status(client, inp, API_KEY)

        assert result.status == "active"
        assert result.delivery_count == 42


class TestCheckNotifications:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient):
        respx.get(f"{BASE_URL}/api/notifications").mock(
            return_value=httpx.Response(
                200,
                json={
                    "notifications": [
                        {
                            "notificationId": "notif-001",
                            "type": "new_imagery",
                            "monitorId": "mon-001",
                            "payload": {"archiveId": "img-new"},
                            "createdAt": NOW_ISO,
                        }
                    ],
                    "unreadCount": 1,
                },
            )
        )

        result = await monitoring.check_notifications(client, API_KEY)

        assert len(result.notifications) == 1
        assert result.unread_count == 1
        assert result.notifications[0].type == "new_imagery"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    @respx.mock
    @pytest.mark.asyncio
    async def test_http_error_structured(self, client: SkyFiClient):
        """API errors should raise ValueError with structured JSON."""
        respx.get(f"{BASE_URL}/api/archive/bad-id").mock(
            return_value=httpx.Response(
                404,
                json={"error": "not_found", "message": "Archive image not found"},
            )
        )

        inp = GetArchiveDetailsInput(archive_id="bad-id")
        with pytest.raises(ValueError) as exc_info:
            await search.get_archive_details(client, inp, API_KEY)

        error_data = json.loads(str(exc_info.value))
        assert error_data["status_code"] == 404
        assert error_data["error"] == "not_found"

    @respx.mock
    @pytest.mark.asyncio
    async def test_connection_error(self, client: SkyFiClient):
        """Network failures should raise ValueError with connection_error."""
        respx.get(f"{BASE_URL}/api/archive/img-001").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        inp = GetArchiveDetailsInput(archive_id="img-001")
        with pytest.raises(ValueError, match="connection_error"):
            await search.get_archive_details(client, inp, API_KEY)

    @pytest.mark.asyncio
    async def test_missing_location_raises(self, client: SkyFiClient):
        """search_archive with empty location should fail."""
        inp = SearchArchiveInput(location=LocationInput())
        with pytest.raises(ValueError, match="location"):
            await search.search_archive(client, inp, API_KEY)


# ---------------------------------------------------------------------------
# Confirmation module
# ---------------------------------------------------------------------------


class TestConfirmationHelpers:
    def test_require_confirmation_false(self):
        from skyfi_mcp.confirmation import require_confirmation

        assert require_confirmation(False) is False

    def test_require_confirmation_true(self):
        from skyfi_mcp.confirmation import require_confirmation

        assert require_confirmation(True) is True

    def test_build_archive_preview(self):
        from skyfi_mcp.confirmation import build_archive_order_preview

        result = build_archive_order_preview(
            archive_id="img-001",
            price=PriceBreakdown(subtotal=100, total=110),
        )
        assert result.preview is not None
        assert result.confirmation is None
        assert result.preview.order_type == "archive"
        assert "$110.00" in result.preview.message

    def test_build_tasking_preview(self):
        from skyfi_mcp.confirmation import build_tasking_order_preview

        result = build_tasking_order_preview(
            quote_id="quote-001",
            price=PriceBreakdown(subtotal=500, total=550),
        )
        assert result.preview is not None
        assert result.preview.order_type == "tasking"

    def test_build_order_confirmation(self):
        from skyfi_mcp.confirmation import build_order_confirmation

        result = build_order_confirmation(
            order_id="ord-001",
            price=PriceBreakdown(subtotal=100, total=110),
            estimated_delivery="2-4 hours",
        )
        assert result.confirmation is not None
        assert result.preview is None
        assert result.confirmation.order_id == "ord-001"


# Need to import PriceBreakdown for the confirmation tests
from interfaces import PriceBreakdown
