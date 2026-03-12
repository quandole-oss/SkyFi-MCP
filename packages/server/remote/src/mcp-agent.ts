/**
 * SkyFi MCP Worker — McpAgent Durable Object
 *
 * Extends McpAgent from the Cloudflare Agents SDK to expose all 21 SkyFi
 * MCP tools.  Each tool validates input with zod, then proxies to the
 * Python service via fetch.
 *
 * Section 3.4 Pain Point 1: Use McpAgent (not createMcpHandler) — we need
 * per-session state, SSE, and notification queues.
 */

import { McpAgent } from "agents/mcp";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import type { Env, Props } from "./types.js";
import { proxyToolCall } from "./proxy.js";

// ---------------------------------------------------------------------------
// Reusable zod schemas
// ---------------------------------------------------------------------------

const GeoJSONGeometrySchema = z.object({
  type: z.string().describe("GeoJSON geometry type"),
  coordinates: z.any().describe("Coordinate array per GeoJSON spec"),
});

const LocationInputSchema = z.object({
  geometry: GeoJSONGeometrySchema.optional().describe("GeoJSON geometry for the AOI"),
  address: z.string().optional().describe("Text address or place name"),
});

const DateRangeSchema = z.object({
  start: z.string().describe("Start date (ISO 8601, inclusive)"),
  end: z.string().describe("End date (ISO 8601, inclusive)"),
});

const DeliveryOptionsSchema = z.object({
  format: z
    .enum(["geotiff", "jpeg2000", "png", "cog"])
    .default("geotiff")
    .describe("Delivery format"),
  projection: z.string().default("EPSG:4326").describe("Target CRS"),
});

// ---------------------------------------------------------------------------
// Annotation presets
// ---------------------------------------------------------------------------

const READ_ONLY = {
  readOnlyHint: true as const,
  destructiveHint: false as const,
  idempotentHint: true as const,
  openWorldHint: true as const,
};

const READ_ONLY_NON_IDEMPOTENT = {
  readOnlyHint: true as const,
  destructiveHint: false as const,
  idempotentHint: false as const,
  openWorldHint: true as const,
};

const DESTRUCTIVE = {
  readOnlyHint: false as const,
  destructiveHint: true as const,
  idempotentHint: false as const,
  openWorldHint: true as const,
};

const CREATE = {
  readOnlyHint: false as const,
  destructiveHint: false as const,
  idempotentHint: false as const,
  openWorldHint: true as const,
};

// ---------------------------------------------------------------------------
// Helper: call a tool via the Python proxy
// ---------------------------------------------------------------------------

type ToolCallbackExtra = { toolName: string };

// ---------------------------------------------------------------------------
// SkyFiMCP Durable Object
// ---------------------------------------------------------------------------

export class SkyFiMCP extends McpAgent<Env, {}, Props> {
  server = new McpServer({
    name: "skyfi_mcp",
    version: "1.0.0",
  });

  async init() {
    // Convenience: proxy a tool call to the Python service
    const proxy = async (
      toolName: string,
      input: Record<string, unknown>,
    ) => {
      const result = await proxyToolCall(this.env.SKYFI_API_BASE_URL, {
        toolName,
        input,
        apiKey: this.props.skyfiApiKey,
      });

      if (!result.ok) {
        return {
          content: [
            {
              type: "text" as const,
              text: JSON.stringify(result.data),
            },
          ],
          isError: true,
        };
      }

      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify(result.data),
          },
        ],
      };
    };

    // -----------------------------------------------------------------------
    // Search & Discovery
    // -----------------------------------------------------------------------

    this.server.tool(
      "search_archive",
      "Search SkyFi's satellite imagery archive by location, date range, resolution, sensor type, and cloud cover.",
      {
        location: LocationInputSchema,
        date_range: DateRangeSchema.optional(),
        resolution_min: z.number().optional().describe("Minimum resolution in meters"),
        sensor_type: z
          .enum(["optical", "sar", "multispectral", "hyperspectral"])
          .optional()
          .describe("Sensor type filter"),
        cloud_cover_max: z
          .number()
          .min(0)
          .max(100)
          .optional()
          .describe("Maximum cloud cover percentage"),
        open_data: z.boolean().optional().describe("Only free/open-data results"),
        page_token: z.string().optional().describe("Pagination token"),
      },
      async (input) => proxy("search_archive", input),
      { annotations: READ_ONLY },
    );

    this.server.tool(
      "get_archive_details",
      "Get detailed metadata for a specific archive image.",
      {
        archive_id: z.string().describe("Unique archive image identifier"),
      },
      async (input) => proxy("get_archive_details", input),
      { annotations: READ_ONLY },
    );

    this.server.tool(
      "explore_providers",
      "List available satellite imagery providers, optionally filtered by location and sensor type.",
      {
        location: LocationInputSchema.optional(),
        sensor_type: z
          .enum(["optical", "sar", "multispectral", "hyperspectral"])
          .optional()
          .describe("Sensor type filter"),
      },
      async (input) => proxy("explore_providers", input),
      { annotations: READ_ONLY },
    );

    // -----------------------------------------------------------------------
    // Pricing & Feasibility
    // -----------------------------------------------------------------------

    this.server.tool(
      "estimate_archive_price",
      "Get an estimated price for purchasing an archive image.",
      {
        archive_id: z.string().describe("Archive image ID to price"),
        delivery_options: DeliveryOptionsSchema.optional(),
      },
      async (input) => proxy("estimate_archive_price", input),
      { annotations: READ_ONLY },
    );

    this.server.tool(
      "get_tasking_quote",
      "Request a quote for a new satellite capture over a specified area.",
      {
        location: LocationInputSchema,
        resolution: z.number().describe("Desired resolution in meters"),
        sensor_type: z
          .enum(["optical", "sar", "multispectral", "hyperspectral"])
          .optional(),
        time_window: DateRangeSchema.optional().describe("Acceptable capture window"),
      },
      async (input) => proxy("get_tasking_quote", input),
      { annotations: READ_ONLY_NON_IDEMPOTENT },
    );

    this.server.tool(
      "analyze_feasibility",
      "Analyze feasibility of capturing new imagery over an area.",
      {
        location: LocationInputSchema,
        time_window: DateRangeSchema.optional(),
        resolution: z.number().optional().describe("Target resolution in meters"),
      },
      async (input) => proxy("analyze_feasibility", input),
      { annotations: READ_ONLY_NON_IDEMPOTENT },
    );

    this.server.tool(
      "compare_pricing",
      "Compare prices across providers and resolution levels for a given area.",
      {
        location: LocationInputSchema,
        resolution_options: z
          .array(z.number())
          .describe("Resolution values in meters to compare"),
      },
      async (input) => proxy("compare_pricing", input),
      { annotations: READ_ONLY },
    );

    // -----------------------------------------------------------------------
    // Order Management
    // -----------------------------------------------------------------------

    this.server.tool(
      "place_archive_order",
      "Place an order for an archive image. Call with confirmed=false first to preview, then confirmed=true to execute.",
      {
        archive_id: z.string().describe("Archive image ID to order"),
        delivery_options: DeliveryOptionsSchema.optional(),
        confirmed: z
          .boolean()
          .default(false)
          .describe("Must be true to execute the order"),
      },
      async (input) => proxy("place_archive_order", input),
      { annotations: DESTRUCTIVE },
    );

    this.server.tool(
      "place_tasking_order",
      "Place a tasking order using a quote ID. Call with confirmed=false first to review, then confirmed=true to execute.",
      {
        quote_id: z.string().describe("Quote ID from get_tasking_quote"),
        confirmed: z
          .boolean()
          .default(false)
          .describe("Must be true to execute the order"),
      },
      async (input) => proxy("place_tasking_order", input),
      { annotations: DESTRUCTIVE },
    );

    this.server.tool(
      "get_order_status",
      "Check the current status and details of an existing order.",
      {
        order_id: z.string().describe("Order ID to check"),
      },
      async (input) => proxy("get_order_status", input),
      { annotations: READ_ONLY },
    );

    this.server.tool(
      "list_orders",
      "List your orders, optionally filtered by status and date range.",
      {
        status: z
          .enum(["pending", "confirmed", "processing", "delivered", "cancelled", "failed"])
          .optional()
          .describe("Filter by order status"),
        date_range: DateRangeSchema.optional(),
        page: z.number().int().min(1).default(1).describe("Page number (1-indexed)"),
      },
      async (input) => proxy("list_orders", input),
      { annotations: READ_ONLY },
    );

    this.server.tool(
      "get_order_images",
      "Retrieve download URLs for imagery delivered as part of an order.",
      {
        order_id: z.string().describe("Order ID to fetch imagery for"),
      },
      async (input) => proxy("get_order_images", input),
      { annotations: READ_ONLY },
    );

    // -----------------------------------------------------------------------
    // Monitoring & Notifications
    // -----------------------------------------------------------------------

    this.server.tool(
      "setup_aoi_monitoring",
      "Set up automated monitoring for new imagery over an area of interest.",
      {
        location: LocationInputSchema,
        resolution_min: z.number().optional().describe("Minimum resolution threshold"),
        notification_url: z.string().optional().describe("Webhook URL for push notifications"),
      },
      async (input) => proxy("setup_aoi_monitoring", input),
      { annotations: CREATE },
    );

    this.server.tool(
      "list_monitors",
      "List all active AOI monitors on your account.",
      {},
      async (input) => proxy("list_monitors", input),
      { annotations: READ_ONLY },
    );

    this.server.tool(
      "delete_monitor",
      "Delete an existing AOI monitor by its ID.",
      {
        monitor_id: z.string().describe("Monitor ID to remove"),
      },
      async (input) => proxy("delete_monitor", input),
      { annotations: DESTRUCTIVE },
    );

    this.server.tool(
      "get_webhook_status",
      "Check the delivery status and health of a webhook subscription.",
      {
        subscription_id: z.string().describe("Webhook subscription ID"),
      },
      async (input) => proxy("get_webhook_status", input),
      { annotations: READ_ONLY },
    );

    this.server.tool(
      "check_notifications",
      "Check for unread notifications (new imagery alerts, order updates).",
      {},
      async (input) => proxy("check_notifications", input),
      { annotations: READ_ONLY },
    );

    // -----------------------------------------------------------------------
    // Geospatial Utilities
    // -----------------------------------------------------------------------

    this.server.tool(
      "geocode",
      "Convert an address or place name to geographic coordinates (OpenStreetMap Nominatim).",
      {
        query: z.string().describe("Address or place name to geocode"),
      },
      async (input) => proxy("geocode", input),
      { annotations: READ_ONLY },
    );

    this.server.tool(
      "reverse_geocode",
      "Convert geographic coordinates to a human-readable address (OpenStreetMap Nominatim).",
      {
        lat: z.number().min(-90).max(90).describe("Latitude"),
        lon: z.number().min(-180).max(180).describe("Longitude"),
      },
      async (input) => proxy("reverse_geocode", input),
      { annotations: READ_ONLY },
    );

    this.server.tool(
      "search_pois",
      "Search for points of interest near a location within a given radius (OpenStreetMap).",
      {
        location: LocationInputSchema,
        category: z
          .enum([
            "airport",
            "port",
            "military",
            "industrial",
            "commercial",
            "residential",
            "natural",
            "water",
            "transportation",
          ])
          .optional()
          .describe("POI category filter"),
        radius: z
          .number()
          .positive()
          .max(50000)
          .default(1000)
          .describe("Search radius in meters"),
      },
      async (input) => proxy("search_pois", input),
      { annotations: READ_ONLY },
    );

    this.server.tool(
      "get_area_boundary",
      "Get the boundary polygon for a named area (city, park, country, etc.) from OpenStreetMap.",
      {
        name: z.string().describe("Name of the area"),
        admin_level: z
          .number()
          .int()
          .min(1)
          .max(11)
          .optional()
          .describe("OSM admin level (2=country, 4=state, 6=county, 8=city)"),
      },
      async (input) => proxy("get_area_boundary", input),
      { annotations: READ_ONLY },
    );
  }
}
