# SkyFi MCP Server -- API Reference

Complete reference for all 21 tools provided by the SkyFi MCP server.

## Table of Contents

- [Search & Discovery](#search--discovery)
  - [search_archive](#search_archive)
  - [get_archive_details](#get_archive_details)
  - [explore_providers](#explore_providers)
- [Pricing & Feasibility](#pricing--feasibility)
  - [estimate_archive_price](#estimate_archive_price)
  - [get_tasking_quote](#get_tasking_quote)
  - [analyze_feasibility](#analyze_feasibility)
  - [compare_pricing](#compare_pricing)
- [Order Management](#order-management)
  - [place_archive_order](#place_archive_order)
  - [place_tasking_order](#place_tasking_order)
  - [get_order_status](#get_order_status)
  - [list_orders](#list_orders)
  - [get_order_images](#get_order_images)
- [Monitoring & Notifications](#monitoring--notifications)
  - [setup_aoi_monitoring](#setup_aoi_monitoring)
  - [list_monitors](#list_monitors)
  - [delete_monitor](#delete_monitor)
  - [get_webhook_status](#get_webhook_status)
  - [check_notifications](#check_notifications)
- [Geospatial Utilities](#geospatial-utilities)
  - [geocode](#geocode)
  - [reverse_geocode](#reverse_geocode)
  - [search_pois](#search_pois)
  - [get_area_boundary](#get_area_boundary)
- [Shared Types](#shared-types)

---

## Search & Discovery

### search_archive

Search the SkyFi archive catalogue for imagery matching spatial, temporal, and sensor criteria.

**Annotations:** `readOnlyHint: true`, `idempotentHint: true`, `openWorldHint: true`

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `location` | LocationInput | Yes | Area of interest as GeoJSON geometry or address string |
| `date_range` | DateRange | No | Temporal window to constrain capture dates |
| `resolution_min` | number | No | Minimum spatial resolution in metres per pixel |
| `sensor_type` | SensorType | No | Filter by sensor modality: `optical`, `sar`, `multispectral`, `hyperspectral` |
| `cloud_cover_max` | number (0-100) | No | Maximum acceptable cloud cover percentage |
| `open_data` | boolean | No | When true, restrict results to openly licensed data |
| `page_token` | string | No | Pagination cursor from a previous search response |

#### Returns

| Field | Type | Description |
|-------|------|-------------|
| `results` | ArchiveResult[] | Matching archive images for the current page |
| `pagination` | PaginationInfo | Pagination metadata (has_more, next_offset, total_count) |

#### Example

```json
// Request
{
  "location": {"address": "San Francisco, CA"},
  "date_range": {"start": "2025-01-01T00:00:00Z", "end": "2025-06-01T00:00:00Z"},
  "sensor_type": "optical",
  "cloud_cover_max": 20
}

// Response
{
  "results": [
    {
      "archive_id": "img-sf-001",
      "provider": "Maxar",
      "sensor_type": "optical",
      "resolution": 0.5,
      "capture_date": "2025-04-15T10:30:00Z",
      "cloud_cover": 8.0,
      "geometry": {"type": "Polygon", "coordinates": [...]},
      "thumbnail_url": "https://cdn.skyfi.com/thumb/img-sf-001.png",
      "open_data": false
    }
  ],
  "pagination": {
    "has_more": false,
    "next_offset": null,
    "total_count": 1
  }
}
```

---

### get_archive_details

Retrieve full metadata for a single archive image.

**Annotations:** `readOnlyHint: true`, `idempotentHint: true`, `openWorldHint: true`

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `archive_id` | string | Yes | Unique identifier of the archive image |

#### Returns

| Field | Type | Description |
|-------|------|-------------|
| `archive_id` | string | Unique image identifier |
| `provider` | string | Imagery provider name |
| `sensor_type` | SensorType | Sensor modality |
| `resolution` | number | Ground resolution in metres per pixel |
| `capture_date` | string (ISO 8601) | Date of image capture |
| `cloud_cover` | number | Cloud cover percentage (0-100) |
| `geometry` | GeoJSONGeometry | Image footprint |
| `bands` | string[] | Spectral bands available (e.g. `["R", "G", "B", "NIR"]`) |
| `file_size_mb` | number | File size in megabytes |
| `license` | string | Licence under which the imagery may be used |
| `metadata` | object | Provider-specific metadata |

#### Example

```json
// Request
{"archive_id": "img-sf-001"}

// Response
{
  "archive_id": "img-sf-001",
  "provider": "Maxar",
  "sensor_type": "multispectral",
  "resolution": 0.3,
  "capture_date": "2025-04-15T10:30:00Z",
  "cloud_cover": 5.0,
  "geometry": {"type": "Polygon", "coordinates": [...]},
  "bands": ["R", "G", "B", "NIR"],
  "file_size_mb": 256.5,
  "license": "commercial",
  "metadata": {"satellite": "WorldView-3"}
}
```

---

### explore_providers

List satellite imagery providers, optionally filtered by location or sensor type.

**Annotations:** `readOnlyHint: true`, `idempotentHint: true`, `openWorldHint: true`

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `location` | LocationInput | No | Filter providers with coverage in this area |
| `sensor_type` | SensorType | No | Filter by sensor modality |

#### Returns

| Field | Type | Description |
|-------|------|-------------|
| `providers` | ProviderInfo[] | Matching providers with name, sensor types, resolution range |

#### Example

```json
// Request
{"sensor_type": "optical"}

// Response
{
  "providers": [
    {
      "provider_id": "maxar",
      "name": "Maxar Technologies",
      "sensor_types": ["optical", "multispectral"],
      "resolution_range": {"min": 0.3, "max": 1.0},
      "coverage_description": "Global"
    },
    {
      "provider_id": "planet",
      "name": "Planet Labs",
      "sensor_types": ["optical"],
      "resolution_range": {"min": 3.0, "max": 5.0},
      "coverage_description": "Daily global coverage"
    }
  ]
}
```

---

## Pricing & Feasibility

### estimate_archive_price

Get a price estimate for purchasing an archive image.

**Annotations:** `readOnlyHint: true`, `idempotentHint: true`, `openWorldHint: true`

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `archive_id` | string | Yes | Archive image ID to price |
| `delivery_options` | DeliveryOptions | No | Delivery format and projection preferences |

#### Returns

| Field | Type | Description |
|-------|------|-------------|
| `archive_id` | string | Image that was priced |
| `price` | PriceBreakdown | Subtotal, processing fee, total, currency |
| `delivery_options` | DeliveryOptions | Format and projection that will be applied |
| `estimated_delivery_time` | string | Human-readable delivery estimate (e.g. "2-4 hours") |

#### Example

```json
// Request
{
  "archive_id": "img-sf-001",
  "delivery_options": {"format": "cog", "projection": "EPSG:4326"}
}

// Response
{
  "archive_id": "img-sf-001",
  "price": {"subtotal": 100.00, "processing_fee": 10.00, "total": 110.00, "currency": "USD"},
  "delivery_options": {"format": "cog", "projection": "EPSG:4326"},
  "estimated_delivery_time": "2-4 hours"
}
```

---

### get_tasking_quote

Request a quote for a new satellite tasking (future capture) over a given area.

**Annotations:** `readOnlyHint: true`, `idempotentHint: false`, `openWorldHint: true`

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `location` | LocationInput | Yes | Area of interest for the tasking request |
| `resolution` | number | Yes | Desired spatial resolution in metres per pixel |
| `sensor_type` | SensorType | No | Preferred sensor modality |
| `time_window` | DateRange | No | Acceptable capture window |

#### Returns

| Field | Type | Description |
|-------|------|-------------|
| `quote_id` | string | Unique quote identifier (use with `place_tasking_order`) |
| `price` | PriceBreakdown | Price breakdown |
| `feasibility_score` | number (0-1) | Probability of successful capture |
| `estimated_capture_window` | DateRange | Estimated capture window |
| `provider` | string | Provider that will perform the tasking |
| `resolution` | number | Actual resolution in metres |
| `expires_at` | string (ISO 8601) | When this quote expires |

#### Example

```json
// Request
{
  "location": {"address": "Amazon Rainforest, Brazil"},
  "resolution": 0.5,
  "sensor_type": "optical"
}

// Response
{
  "quote_id": "quote-789",
  "price": {"subtotal": 500.00, "processing_fee": 50.00, "total": 550.00, "currency": "USD"},
  "feasibility_score": 0.85,
  "estimated_capture_window": {"start": "2025-06-10T00:00:00Z", "end": "2025-06-20T00:00:00Z"},
  "provider": "Maxar",
  "resolution": 0.5,
  "expires_at": "2025-06-05T00:00:00Z"
}
```

---

### analyze_feasibility

Analyze the feasibility of capturing imagery at a given location within a time window.

**Annotations:** `readOnlyHint: true`, `idempotentHint: false`, `openWorldHint: true`

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `location` | LocationInput | Yes | Area of interest |
| `time_window` | DateRange | No | Desired capture window |
| `resolution` | number | No | Target resolution in metres per pixel |

#### Returns

| Field | Type | Description |
|-------|------|-------------|
| `feasibility_score` | number (0-1) | Overall probability of successful capture |
| `cloud_forecast` | object | Cloud cover forecast (average_cloud_cover, clear_days) |
| `satellite_passes` | object[] | Predicted satellite overpasses (satellite, pass_time, elevation_angle) |
| `capture_windows` | object[] | Ranked capture windows with success probability |
| `recommendations` | string[] | Human-readable recommendations |

#### Example

```json
// Request
{
  "location": {"address": "Lake Tahoe, CA"},
  "time_window": {"start": "2025-06-01T00:00:00Z", "end": "2025-06-15T00:00:00Z"},
  "resolution": 1.0
}

// Response
{
  "feasibility_score": 0.72,
  "cloud_forecast": {"average_cloud_cover": 25.0, "clear_days": 7},
  "satellite_passes": [
    {"satellite": "WV3", "pass_time": "2025-06-03T10:15:00Z", "elevation_angle": 72.5}
  ],
  "capture_windows": [
    {"start": "2025-06-03T00:00:00Z", "end": "2025-06-05T00:00:00Z", "probability": 0.82}
  ],
  "recommendations": ["Consider a wider time window for higher probability."]
}
```

---

### compare_pricing

Compare imagery pricing across providers and resolution tiers for a given location.

**Annotations:** `readOnlyHint: true`, `idempotentHint: true`, `openWorldHint: true`

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `location` | LocationInput | Yes | Area of interest |
| `resolution_options` | number[] | Yes | List of resolution values (metres) to compare |

#### Returns

| Field | Type | Description |
|-------|------|-------------|
| `comparisons` | PricingComparison[] | Provider/resolution price points |
| `recommended` | PricingComparison | Best-value recommendation with reason |

#### Example

```json
// Request
{"location": {"address": "Tokyo, Japan"}, "resolution_options": [0.5, 3.0]}

// Response
{
  "comparisons": [
    {"provider": "Maxar", "resolution": 0.5, "price": {"subtotal": 100, "total": 110}, "sensor_type": "optical"},
    {"provider": "Planet", "resolution": 3.0, "price": {"subtotal": 30, "total": 33}, "sensor_type": "optical"}
  ],
  "recommended": {
    "provider": "Planet", "resolution": 3.0,
    "price": {"subtotal": 30, "total": 33}, "sensor_type": "optical",
    "reason": "Best price-to-resolution ratio for this area."
  }
}
```

---

## Order Management

### place_archive_order

Place (or preview) an order for an archive image. **Requires two-step confirmation.**

**Annotations:** `destructiveHint: true`, `openWorldHint: true`

**Confirmation flow:**
1. Call with `confirmed: false` (or omit) to get a price preview.
2. Present the preview to the user.
3. Call again with `confirmed: true` only after user approval.

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `archive_id` | string | Yes | Archive image ID to order |
| `delivery_options` | DeliveryOptions | No | Delivery format and projection |
| `confirmed` | boolean | No | Must be `true` to execute. Default `false` returns preview only |

#### Returns (Preview -- confirmed=false)

| Field | Type | Description |
|-------|------|-------------|
| `order_type` | string | Always `"archive"` |
| `price` | PriceBreakdown | Price breakdown |
| `details` | object | Order details (archive_id, delivery options, metadata) |
| `message` | string | Human-readable confirmation prompt |

#### Returns (Confirmation -- confirmed=true)

| Field | Type | Description |
|-------|------|-------------|
| `order_id` | string | Unique order identifier |
| `status` | OrderStatus | Order status (typically `"confirmed"`) |
| `price` | PriceBreakdown | Final price |
| `estimated_delivery` | string | Estimated delivery time |
| `message` | string | Confirmation message |

#### Example

```json
// Step 1: Preview
{"archive_id": "img-sf-001", "confirmed": false}

// Preview Response
{
  "order_type": "archive",
  "price": {"subtotal": 100.00, "processing_fee": 10.00, "total": 110.00, "currency": "USD"},
  "details": {"archive_id": "img-sf-001", "estimated_delivery_time": "2-4 hours"},
  "message": "Archive order for image img-sf-001. Total cost: $110.00 USD. Please confirm by calling again with confirmed=true."
}

// Step 2: Confirm
{"archive_id": "img-sf-001", "confirmed": true}

// Confirmation Response
{
  "order_id": "ord-001",
  "status": "confirmed",
  "price": {"subtotal": 100.00, "processing_fee": 10.00, "total": 110.00, "currency": "USD"},
  "estimated_delivery": "2-4 hours",
  "message": "Order ord-001 placed successfully."
}
```

---

### place_tasking_order

Place (or preview) a tasking order from a previously obtained quote. **Requires two-step confirmation.**

**Annotations:** `destructiveHint: true`, `openWorldHint: true`

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `quote_id` | string | Yes | Quote ID from `get_tasking_quote` |
| `confirmed` | boolean | No | Must be `true` to execute. Default `false` returns preview only |

#### Returns

Same structure as `place_archive_order` -- preview when `confirmed=false`, confirmation when `confirmed=true`.

#### Example

```json
// Preview
{"quote_id": "quote-789", "confirmed": false}

// Confirm
{"quote_id": "quote-789", "confirmed": true}
```

---

### get_order_status

Retrieve the current status and metadata of an order.

**Annotations:** `readOnlyHint: true`, `idempotentHint: true`, `openWorldHint: true`

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `order_id` | string | Yes | Unique order identifier |

#### Returns

| Field | Type | Description |
|-------|------|-------------|
| `order_id` | string | Order identifier |
| `status` | OrderStatus | `pending`, `confirmed`, `processing`, `delivered`, `cancelled`, `failed` |
| `created_at` | string (ISO 8601) | Creation timestamp |
| `updated_at` | string (ISO 8601) | Last update timestamp |
| `price` | PriceBreakdown | Order price |
| `delivery_urls` | string[] | Download URLs (when status is `delivered`) |
| `metadata` | object | Additional order metadata |

#### Example

```json
// Request: {{"order_id": "ord-001"}}
// Response
{
  "order_id": "ord-001",
  "status": "delivered",
  "created_at": "2025-06-01T12:00:00Z",
  "updated_at": "2025-06-01T14:30:00Z",
  "price": {"subtotal": 100, "processing_fee": 10, "total": 110, "currency": "USD"},
  "delivery_urls": ["https://cdn.skyfi.com/orders/ord-001/image.tif"],
  "metadata": {"provider": "Maxar", "resolution": 0.5}
}
```

---

### list_orders

List orders, optionally filtered by status and/or date range.

**Annotations:** `readOnlyHint: true`, `idempotentHint: true`, `openWorldHint: true`

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `status` | OrderStatus | No | Filter by order lifecycle status |
| `date_range` | DateRange | No | Filter by creation date |
| `page` | integer (>= 1) | No | Page number, default 1 |

#### Returns

| Field | Type | Description |
|-------|------|-------------|
| `orders` | OrderSummary[] | Orders on the current page |
| `pagination` | PaginationInfo | Pagination metadata |

---

### get_order_images

Retrieve download URLs for imagery delivered as part of an order.

**Annotations:** `readOnlyHint: true`, `idempotentHint: true`, `openWorldHint: true`

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `order_id` | string | Yes | Order ID to fetch imagery for |

#### Returns

| Field | Type | Description |
|-------|------|-------------|
| `order_id` | string | Order identifier |
| `images` | object[] | Array of `{url, format, size_mb}` objects |

#### Example

```json
// Response
{
  "order_id": "ord-001",
  "images": [
    {"url": "https://cdn.skyfi.com/img.tif", "format": "geotiff", "size_mb": 128.0}
  ]
}
```

---

## Monitoring & Notifications

### setup_aoi_monitoring

Create a persistent monitor that watches for new imagery over an area of interest.

**Annotations:** `readOnlyHint: false`, `destructiveHint: false`, `openWorldHint: true`

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `location` | LocationInput | Yes | Area of interest to monitor |
| `resolution_min` | number | No | Minimum acceptable resolution in metres |
| `notification_url` | string (URI) | No | Webhook URL for push notifications |

#### Returns

| Field | Type | Description |
|-------|------|-------------|
| `monitor` | MonitorInfo | The newly created monitor (monitor_id, location, status) |
| `message` | string | Confirmation message |

---

### list_monitors

List all active area-of-interest monitors.

**Annotations:** `readOnlyHint: true`, `idempotentHint: true`, `openWorldHint: true`

#### Parameters

None.

#### Returns

| Field | Type | Description |
|-------|------|-------------|
| `monitors` | MonitorInfo[] | Active monitors |

---

### delete_monitor

Delete an area-of-interest monitor.

**Annotations:** `destructiveHint: true`, `openWorldHint: true`

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `monitor_id` | string | Yes | Monitor ID to delete |

#### Returns

| Field | Type | Description |
|-------|------|-------------|
| `monitor_id` | string | Deleted monitor ID |
| `deleted` | boolean | True if successfully deleted |
| `message` | string | Confirmation message |

---

### get_webhook_status

Check the delivery status and health of a webhook subscription.

**Annotations:** `readOnlyHint: true`, `idempotentHint: true`, `openWorldHint: true`

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `subscription_id` | string | Yes | Webhook subscription ID |

#### Returns

| Field | Type | Description |
|-------|------|-------------|
| `subscription_id` | string | Subscription identifier |
| `status` | string | `active`, `paused`, `error`, `disabled` |
| `last_delivery_at` | string (ISO 8601) or null | Last successful delivery |
| `delivery_count` | integer | Total successful deliveries |
| `failure_count` | integer | Total failed delivery attempts |

---

### check_notifications

Retrieve pending/unread notifications for the authenticated user.

**Annotations:** `readOnlyHint: true`, `idempotentHint: true`, `openWorldHint: true`

#### Parameters

None.

#### Returns

| Field | Type | Description |
|-------|------|-------------|
| `notifications` | Notification[] | List of notifications (notification_id, type, monitor_id, payload, created_at) |
| `unread_count` | integer | Total unread notification count |

---

## Geospatial Utilities

### geocode

Convert a free-text address or place name into geographic coordinates. Uses OpenStreetMap Nominatim.

**Annotations:** `readOnlyHint: true`, `idempotentHint: true`, `openWorldHint: true`

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `query` | string | Yes | Address, place name, or landmark to geocode |

#### Returns

| Field | Type | Description |
|-------|------|-------------|
| `results` | GeocodeResult[] | Matching locations with lat, lon, display_name, geometry, importance |

#### Example

```json
// Request: {{"query": "Eiffel Tower, Paris"}}
// Response
{
  "results": [
    {
      "lat": 48.8584,
      "lon": 2.2945,
      "display_name": "Eiffel Tower, Avenue Anatole France, Paris, France",
      "geometry": {"type": "Point", "coordinates": [2.2945, 48.8584]},
      "osm_type": "way",
      "osm_id": 5013364,
      "importance": 0.82
    }
  ]
}
```

---

### reverse_geocode

Convert geographic coordinates into a human-readable address.

**Annotations:** `readOnlyHint: true`, `idempotentHint: true`, `openWorldHint: true`

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `lat` | number (-90 to 90) | Yes | Latitude in decimal degrees (WGS 84) |
| `lon` | number (-180 to 180) | Yes | Longitude in decimal degrees (WGS 84) |

#### Returns

| Field | Type | Description |
|-------|------|-------------|
| `address` | string | Human-readable address |
| `lat` | number | Latitude that was looked up |
| `lon` | number | Longitude that was looked up |
| `details` | object | Structured address components (road, city, state, country, postcode) |

---

### search_pois

Search for points of interest near a location.

**Annotations:** `readOnlyHint: true`, `idempotentHint: true`, `openWorldHint: true`

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `location` | LocationInput | Yes | Centre point for the POI search |
| `category` | POICategory | No | Filter: `airport`, `port`, `military`, `industrial`, `commercial`, `residential`, `natural`, `water`, `transportation` |
| `radius` | number (0-50000) | No | Search radius in metres, default 1000 |

#### Returns

| Field | Type | Description |
|-------|------|-------------|
| `results` | POIResult[] | Matching POIs with name, category, lat, lon, distance_m, tags |

---

### get_area_boundary

Retrieve the administrative boundary polygon for a named area.

**Annotations:** `readOnlyHint: true`, `idempotentHint: true`, `openWorldHint: true`

#### Parameters

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | Yes | Name of the area (city, county, state, country) |
| `admin_level` | integer (1-11) | No | OSM admin level to disambiguate (2=country, 4=state, 6=county, 8=city) |

#### Returns

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Canonical name of the area |
| `geometry` | GeoJSONGeometry | Boundary polygon/multipolygon |
| `admin_level` | integer | OSM admin level |
| `osm_id` | integer | OpenStreetMap relation ID |

---

## Shared Types

### LocationInput

A location can be specified as either a GeoJSON geometry or a text address:

```json
// As address
{"address": "San Francisco, CA"}

// As GeoJSON geometry
{"type": "Polygon", "coordinates": [[[-122.4, 37.7], [-122.4, 37.8], [-122.3, 37.8], [-122.3, 37.7], [-122.4, 37.7]]]}
```

### DateRange

```json
{"start": "2025-01-01T00:00:00Z", "end": "2025-06-01T00:00:00Z"}
```

### DeliveryOptions

```json
{"format": "geotiff", "projection": "EPSG:4326"}
```

Supported formats: `geotiff`, `jpeg2000`, `png`, `cog` (Cloud-Optimized GeoTIFF).

### PriceBreakdown

```json
{"subtotal": 100.00, "processing_fee": 10.00, "total": 110.00, "currency": "USD"}
```

### SensorType

One of: `optical`, `sar`, `multispectral`, `hyperspectral`.

### OrderStatus

One of: `pending`, `confirmed`, `processing`, `delivered`, `cancelled`, `failed`.

### POICategory

One of: `airport`, `port`, `military`, `industrial`, `commercial`, `residential`, `natural`, `water`, `transportation`.

### PaginationInfo

```json
{"has_more": true, "next_offset": "cursor-abc123", "total_count": 50}
```

Pass `next_offset` as `page_token` in the next request to retrieve the next page.
