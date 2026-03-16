"""
Unit tests for SkyFi MCP tool functions.

Uses ``respx`` to mock httpx requests so no real HTTP calls are made.
Covers:
- Every tool with valid input
- Error cases (API errors, invalid input)
- Confirmation flow (preview vs. execute)
- Search pagination (nextPage handling)

All mocked URLs and response shapes match the real SkyFi Platform API
as documented at https://app.skyfi.com/platform-api/openapi.json.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from skyfi_mcp.client.skyfi import SkyFiClient
from skyfi_mcp.tools import monitoring, orders, pricing, search

from interfaces import (
    AnalyzeFeasibilityInput,
    ComparePricingInput,
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
    PriceBreakdown,
    SearchArchiveInput,
    SensorType,
    SetupAOIMonitoringInput,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE_URL = "https://test.skyfi.local/platform-api"
API_KEY = "test-api-key-do-not-use"

NOW_ISO = "2025-06-01T12:00:00Z"
NOW_DT = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

_FOOTPRINT_WKT = "POLYGON((-122.4 37.7,-122.4 37.8,-122.3 37.8,-122.3 37.7,-122.4 37.7))"


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


def _archive_item(**overrides: object) -> dict:
    """Build a realistic archive result matching the real API shape."""
    item = {
        "archiveId": "img-001",
        "provider": "SATELLOGIC",
        "constellation": "newsat",
        "productType": "DAY",
        "platformResolution": 1.0,
        "resolution": "VERY HIGH",
        "captureTimestamp": NOW_ISO,
        "cloudCoveragePercent": 10.0,
        "offNadirAngle": 15.0,
        "footprint": _FOOTPRINT_WKT,
        "minSqKm": 5.0,
        "maxSqKm": 10000.0,
        "priceForOneSquareKm": 5.0,
        "priceForOneSquareKmCents": 500,
        "priceFullScene": 50.0,
        "openData": False,
        "totalAreaSquareKm": 10.0,
        "deliveryTimeHours": 24.0,
        "thumbnailUrls": {"300x300": "https://example.com/thumb.png"},
        "gsd": 1.0,
        "tilesUrl": "https://example.com/tiles/{z}/{x}/{y}.png",
        "overlapRatio": 1.0,
        "overlapSqkm": 10.0,
    }
    item.update(overrides)
    return item


# ---------------------------------------------------------------------------
# Search & Discovery
# ---------------------------------------------------------------------------


class TestSearchArchive:
    @respx.mock
    @pytest.mark.asyncio
    async def test_basic_search(self, client: SkyFiClient, sample_location: LocationInput):
        respx.post(f"{BASE_URL}/archives").mock(
            return_value=httpx.Response(
                200,
                json={
                    "request": {"aoi": _FOOTPRINT_WKT},
                    "archives": [_archive_item()],
                    "nextPage": None,
                    "total": 1,
                },
            )
        )

        inp = SearchArchiveInput(location=sample_location)
        result = await search.search_archive(client, inp, API_KEY)

        assert len(result.results) == 1
        assert result.results[0].archive_id == "img-001"
        assert result.results[0].provider == "SATELLOGIC"
        assert result.results[0].resolution == 1.0
        assert result.pagination.has_more is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_pagination(self, client: SkyFiClient, sample_location: LocationInput):
        """Verify nextPage handling: first page has more, second does not."""
        respx.post(f"{BASE_URL}/archives").mock(
            return_value=httpx.Response(
                200,
                json={
                    "archives": [_archive_item(archiveId="img-page1", provider="Planet")],
                    "total": 50,
                    "nextPage": "/platform-api/archives?page=cursor-abc123",
                },
            )
        )

        inp = SearchArchiveInput(location=sample_location)
        result = await search.search_archive(client, inp, API_KEY)

        assert result.pagination.has_more is True
        assert result.pagination.next_offset == "/platform-api/archives?page=cursor-abc123"

        # Simulate second page via GET /archives?page=...
        respx.get(f"{BASE_URL}/archives").mock(
            return_value=httpx.Response(
                200,
                json={
                    "archives": [_archive_item(archiveId="img-page2", provider="Planet")],
                    "total": 50,
                    "nextPage": None,
                },
            )
        )

        inp2 = SearchArchiveInput(
            location=sample_location,
            page_token="/platform-api/archives?page=cursor-abc123",
        )
        result2 = await search.search_archive(client, inp2, API_KEY)
        assert result2.pagination.has_more is False
        assert result2.results[0].archive_id == "img-page2"

    @respx.mock
    @pytest.mark.asyncio
    async def test_api_error(self, client: SkyFiClient, sample_location: LocationInput):
        respx.post(f"{BASE_URL}/archives").mock(
            return_value=httpx.Response(
                403,
                json={"detail": "Invalid api key"},
            )
        )

        inp = SearchArchiveInput(location=sample_location)
        with pytest.raises(ValueError, match="Invalid api key"):
            await search.search_archive(client, inp, API_KEY)


class TestGetArchiveDetails:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient):
        respx.get(f"{BASE_URL}/archives/img-001").mock(
            return_value=httpx.Response(
                200,
                json=_archive_item(
                    productType="MULTISPECTRAL",
                    gsd=0.3,
                ),
            )
        )

        inp = GetArchiveDetailsInput(archive_id="img-001")
        result = await search.get_archive_details(client, inp, API_KEY)

        assert result.archive_id == "img-001"
        assert result.sensor_type == SensorType.MULTISPECTRAL
        assert result.resolution == 0.3
        assert result.thumbnail_url == "https://example.com/thumb.png"

    @respx.mock
    @pytest.mark.asyncio
    async def test_thumbnail_url_missing(self, client: SkyFiClient):
        """thumbnail_url should be None when API omits thumbnailUrls."""
        respx.get(f"{BASE_URL}/archives/img-002").mock(
            return_value=httpx.Response(
                200,
                json=_archive_item(
                    archiveId="img-002",
                    thumbnailUrls={},
                ),
            )
        )

        inp = GetArchiveDetailsInput(archive_id="img-002")
        result = await search.get_archive_details(client, inp, API_KEY)

        assert result.archive_id == "img-002"
        assert result.thumbnail_url is None


class TestExploreProviders:
    @pytest.mark.asyncio
    async def test_list_all(self, client: SkyFiClient):
        """explore_providers returns the known provider list (no API call)."""
        inp = ExploreProvidersInput()
        result = await search.explore_providers(client, inp, API_KEY)

        assert len(result.providers) > 0
        provider_ids = [p.provider_id for p in result.providers]
        assert "PLANET" in provider_ids
        assert "UMBRA" in provider_ids

    @pytest.mark.asyncio
    async def test_filter_by_sensor(self, client: SkyFiClient):
        inp = ExploreProvidersInput(sensor_type=SensorType.SAR)
        result = await search.explore_providers(client, inp, API_KEY)

        for p in result.providers:
            assert SensorType.SAR in p.sensor_types


# ---------------------------------------------------------------------------
# Pricing & Feasibility
# ---------------------------------------------------------------------------


class TestEstimateArchivePrice:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient):
        respx.get(f"{BASE_URL}/archives/img-001").mock(
            return_value=httpx.Response(
                200,
                json=_archive_item(
                    priceForOneSquareKm=5.0,
                    priceFullScene=50.0,
                    deliveryTimeHours=24,
                ),
            )
        )

        inp = EstimateArchivePriceInput(
            archive_id="img-001",
            delivery_options=DeliveryOptions(format=DeliveryFormat.COG),
        )
        result = await pricing.estimate_archive_price(client, inp, API_KEY)

        assert result.archive_id == "img-001"
        assert result.price.subtotal == 5.0
        assert result.price.total == 50.0
        assert "24" in (result.estimated_delivery_time or "")


class TestGetTaskingQuote:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient, sample_location: LocationInput):
        respx.post(f"{BASE_URL}/pricing").mock(
            return_value=httpx.Response(
                200,
                json={
                    "quoteId": "pricing-estimate",
                    "subtotal": 500.0,
                    "total": 550.0,
                    "provider": "PLANET",
                    "resolution": "HIGH",
                },
            )
        )

        inp = GetTaskingQuoteInput(
            location=sample_location,
            resolution=0.5,
            sensor_type=SensorType.OPTICAL,
        )
        result = await pricing.get_tasking_quote(client, inp, API_KEY)

        assert result.price.subtotal == 500.0
        assert result.price.total == 550.0


class TestAnalyzeFeasibility:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient, sample_location: LocationInput):
        respx.post(f"{BASE_URL}/feasibility").mock(
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


class TestComparePricing:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient, sample_location: LocationInput):
        respx.post(f"{BASE_URL}/pricing").mock(
            return_value=httpx.Response(
                200,
                json={
                    "options": [
                        {
                            "provider": "PLANET",
                            "gsd": 3.0,
                            "subtotal": 30,
                            "total": 33,
                        },
                        {
                            "provider": "SATELLOGIC",
                            "gsd": 1.0,
                            "subtotal": 100,
                            "total": 110,
                        },
                    ],
                },
            )
        )

        inp = ComparePricingInput(
            location=sample_location, resolution_options=[0.5, 3.0]
        )
        result = await pricing.compare_pricing(client, inp, API_KEY)

        assert len(result.comparisons) == 2
        assert result.recommended is not None


# ---------------------------------------------------------------------------
# Order Management — Confirmation flow
# ---------------------------------------------------------------------------


class TestPlaceArchiveOrder:
    @respx.mock
    @pytest.mark.asyncio
    async def test_preview_when_not_confirmed(self, client: SkyFiClient):
        """confirmed=False should return a preview, NOT place the order."""
        respx.get(f"{BASE_URL}/archives/img-001").mock(
            return_value=httpx.Response(200, json=_archive_item())
        )

        inp = PlaceArchiveOrderInput(archive_id="img-001", confirmed=False)
        result = await orders.place_archive_order(client, inp, API_KEY)

        # Must be a preview, not a confirmation
        assert result.preview is not None
        assert result.confirmation is None
        assert result.preview.order_type == "archive"
        assert "confirm" in result.preview.message.lower()

    @respx.mock
    @pytest.mark.asyncio
    async def test_preview_details_accepts_thumbnail_included(self, client: SkyFiClient):
        """preview.details should accept thumbnail_included flag set by the server layer."""
        respx.get(f"{BASE_URL}/archives/img-001").mock(
            return_value=httpx.Response(200, json=_archive_item())
        )

        inp = PlaceArchiveOrderInput(archive_id="img-001", confirmed=False)
        result = await orders.place_archive_order(client, inp, API_KEY)

        assert result.preview is not None
        # Server layer sets this flag after enrichment; verify details is mutable
        result.preview.details["thumbnail_included"] = False
        assert result.preview.details["thumbnail_included"] is False

        result.preview.details["thumbnail_included"] = True
        assert result.preview.details["thumbnail_included"] is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_preview_no_thumbnail_url(self, client: SkyFiClient):
        """Archives without thumbnailUrls should still produce a valid preview."""
        respx.get(f"{BASE_URL}/archives/img-sar").mock(
            return_value=httpx.Response(
                200,
                json=_archive_item(archiveId="img-sar", thumbnailUrls={}),
            )
        )

        inp = PlaceArchiveOrderInput(archive_id="img-sar", confirmed=False)
        result = await orders.place_archive_order(client, inp, API_KEY)

        assert result.preview is not None
        assert result.confirmation is None
        # No thumbnail URL means server will set thumbnail_included=False
        assert "thumbnail_included" not in result.preview.details

    @respx.mock
    @pytest.mark.asyncio
    async def test_preview_default_confirmed(self, client: SkyFiClient):
        """Default (no confirmed kwarg) should also return preview."""
        respx.get(f"{BASE_URL}/archives/img-001").mock(
            return_value=httpx.Response(200, json=_archive_item())
        )

        inp = PlaceArchiveOrderInput(archive_id="img-001")
        result = await orders.place_archive_order(client, inp, API_KEY)

        assert result.preview is not None
        assert result.confirmation is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_when_confirmed(self, client: SkyFiClient):
        """confirmed=True should actually place the order."""
        respx.get(f"{BASE_URL}/archives/img-001").mock(
            return_value=httpx.Response(200, json=_archive_item())
        )
        respx.post(f"{BASE_URL}/order-archive").mock(
            return_value=httpx.Response(
                200,
                json={
                    "orderId": "ord-001",
                    "estimatedDelivery": "24 hours",
                },
            )
        )

        inp = PlaceArchiveOrderInput(archive_id="img-001", confirmed=True)
        result = await orders.place_archive_order(client, inp, API_KEY)

        assert result.confirmation is not None
        assert result.preview is None
        assert result.confirmation.order_id == "ord-001"


class TestPlaceTaskingOrder:
    @respx.mock
    @pytest.mark.asyncio
    async def test_preview_when_not_confirmed(
        self, client: SkyFiClient, sample_location: LocationInput
    ):
        respx.post(f"{BASE_URL}/pricing").mock(
            return_value=httpx.Response(
                200,
                json={"subtotal": 500, "total": 550},
            )
        )

        now = datetime.now(UTC)
        inp = PlaceTaskingOrderInput(
            location=sample_location,
            window_start=now,
            window_end=now + timedelta(days=7),
            product_type="DAY",
            resolution="HIGH",
            confirmed=False,
        )
        result = await orders.place_tasking_order(client, inp, API_KEY)

        assert result.preview is not None
        assert result.confirmation is None
        assert result.preview.order_type == "tasking"

    @respx.mock
    @pytest.mark.asyncio
    async def test_execute_when_confirmed(
        self, client: SkyFiClient, sample_location: LocationInput
    ):
        respx.post(f"{BASE_URL}/pricing").mock(
            return_value=httpx.Response(
                200,
                json={"subtotal": 500, "total": 550},
            )
        )
        respx.post(f"{BASE_URL}/order-tasking").mock(
            return_value=httpx.Response(
                200,
                json={
                    "orderId": "ord-task-001",
                    "estimatedDelivery": "3-5 days",
                },
            )
        )

        now = datetime.now(UTC)
        inp = PlaceTaskingOrderInput(
            location=sample_location,
            window_start=now,
            window_end=now + timedelta(days=7),
            product_type="DAY",
            resolution="HIGH",
            confirmed=True,
        )
        result = await orders.place_tasking_order(client, inp, API_KEY)

        assert result.confirmation is not None
        assert result.confirmation.order_id == "ord-task-001"


class TestGetOrderStatus:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient):
        respx.get(f"{BASE_URL}/orders/ord-001").mock(
            return_value=httpx.Response(
                200,
                json={
                    "orderId": "ord-001",
                    "deliveryStatus": "DELIVERY_COMPLETED",
                    "createdAt": NOW_ISO,
                    "lastModified": NOW_ISO,
                    "customerItemCost": 110.0,
                },
            )
        )

        inp = GetOrderStatusInput(order_id="ord-001")
        result = await orders.get_order_status(client, inp, API_KEY)

        assert result.order_id == "ord-001"
        assert result.status.value == "delivered"


class TestListOrders:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient):
        respx.get(f"{BASE_URL}/orders").mock(
            return_value=httpx.Response(
                200,
                json={
                    "orders": [
                        {
                            "orderId": "ord-001",
                            "deliveryStatus": "DELIVERY_COMPLETED",
                            "createdAt": NOW_ISO,
                            "lastModified": NOW_ISO,
                            "label": "Austin, TX",
                            "aoi": "POLYGON((-97.8 30.2,-97.7 30.2,-97.7 30.3,-97.8 30.3,-97.8 30.2))",
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
        assert result.orders[0].location_name == "Austin, TX"
        assert "aoi" in result.orders[0].metadata


class TestGetOrderImages:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient):
        respx.get(f"{BASE_URL}/orders/ord-001/image").mock(
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


# ---------------------------------------------------------------------------
# Monitoring & Notifications
# ---------------------------------------------------------------------------


class TestSetupAOIMonitoring:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient, sample_location: LocationInput):
        respx.post(f"{BASE_URL}/notifications").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "notif-001",
                    "aoi": _FOOTPRINT_WKT,
                    "webhookUrl": "https://example.com/hook",
                    "createdAt": NOW_ISO,
                    "status": "active",
                },
            )
        )

        inp = SetupAOIMonitoringInput(
            location=sample_location,
            resolution_min=1.0,
            notification_url="https://example.com/hook",
        )
        result = await monitoring.setup_aoi_monitoring(client, inp, API_KEY)

        assert result.monitor.monitor_id == "notif-001"
        assert result.monitor.status == "active"

    @respx.mock
    @pytest.mark.asyncio
    async def test_no_webhook_url(self, client: SkyFiClient, sample_location: LocationInput):
        """When no notification_url is provided, webhookUrl should not be in the body."""
        route = respx.post(f"{BASE_URL}/notifications").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "notif-002",
                    "aoi": _FOOTPRINT_WKT,
                    "createdAt": NOW_ISO,
                    "status": "active",
                },
            )
        )

        inp = SetupAOIMonitoringInput(
            location=sample_location,
            resolution_min=1.0,
        )
        result = await monitoring.setup_aoi_monitoring(client, inp, API_KEY)

        assert result.monitor.monitor_id == "notif-002"
        # Verify the request body did not include webhookUrl
        import json
        sent_body = json.loads(route.calls[0].request.content)
        assert "webhookUrl" not in sent_body


class TestListMonitors:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient):
        respx.get(f"{BASE_URL}/notifications").mock(
            return_value=httpx.Response(
                200,
                json={
                    "notifications": [
                        {
                            "id": "notif-001",
                            "aoi": _FOOTPRINT_WKT,
                            "webhookUrl": "https://example.com/hook",
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
        respx.delete(f"{BASE_URL}/notifications/notif-001").mock(
            return_value=httpx.Response(
                200,
                json={"message": "Notification deleted."},
            )
        )

        inp = DeleteMonitorInput(monitor_id="notif-001")
        result = await monitoring.delete_monitor(client, inp, API_KEY)

        assert result.deleted is True
        assert result.monitor_id == "notif-001"


class TestGetWebhookStatus:
    @respx.mock
    @pytest.mark.asyncio
    async def test_success(self, client: SkyFiClient):
        respx.get(f"{BASE_URL}/notifications/sub-001").mock(
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
        respx.get(f"{BASE_URL}/notifications").mock(
            return_value=httpx.Response(
                200,
                json={
                    "notifications": [
                        {
                            "id": "notif-001",
                            "type": "new_imagery",
                            "aoi": _FOOTPRINT_WKT,
                            "createdAt": NOW_ISO,
                        }
                    ],
                },
            )
        )

        result = await monitoring.check_notifications(client, API_KEY)

        assert len(result.notifications) == 1
        assert result.unread_count == 1


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    @respx.mock
    @pytest.mark.asyncio
    async def test_http_error_structured(self, client: SkyFiClient):
        """API errors should raise ValueError with structured JSON."""
        respx.get(f"{BASE_URL}/archives/bad-id").mock(
            return_value=httpx.Response(
                404,
                json={"detail": "Archive image not found"},
            )
        )

        inp = GetArchiveDetailsInput(archive_id="bad-id")
        with pytest.raises(ValueError, match="not found"):
            await search.get_archive_details(client, inp, API_KEY)

    @respx.mock
    @pytest.mark.asyncio
    async def test_connection_error(self, client: SkyFiClient):
        """Network failures should raise ValueError with connection_error."""
        respx.get(f"{BASE_URL}/archives/img-001").mock(
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
# WKT conversion
# ---------------------------------------------------------------------------


class TestWKTConversion:
    def test_geojson_to_wkt_polygon(self):
        from skyfi_mcp.client.wkt import geojson_to_wkt

        geom = {
            "type": "Polygon",
            "coordinates": [[[-122.4, 37.7], [-122.4, 37.8], [-122.3, 37.7], [-122.4, 37.7]]],
        }
        wkt = geojson_to_wkt(geom)
        assert wkt.startswith("POLYGON(")
        assert "-122.4 37.7" in wkt

    def test_wkt_to_geojson_polygon(self):
        from skyfi_mcp.client.wkt import wkt_to_geojson

        wkt = "POLYGON((-122.4 37.7,-122.4 37.8,-122.3 37.7,-122.4 37.7))"
        geojson = wkt_to_geojson(wkt)
        assert geojson["type"] == "Polygon"
        assert len(geojson["coordinates"]) == 1
        assert len(geojson["coordinates"][0]) == 4

    def test_roundtrip(self):
        from skyfi_mcp.client.wkt import geojson_to_wkt, wkt_to_geojson

        original = {
            "type": "Polygon",
            "coordinates": [
                [[-122.4, 37.7], [-122.4, 37.8], [-122.3, 37.8], [-122.3, 37.7], [-122.4, 37.7]]
            ],
        }
        wkt = geojson_to_wkt(original)
        restored = wkt_to_geojson(wkt)
        assert restored["type"] == "Polygon"
        assert len(restored["coordinates"][0]) == len(original["coordinates"][0])


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
        assert result.confirmation.order_url == "https://app.skyfi.com/orders/ord-001"
        assert "https://app.skyfi.com/orders/ord-001" in result.confirmation.message
