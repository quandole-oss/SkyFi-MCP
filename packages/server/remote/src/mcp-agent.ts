/**
 * SkyFi MCP Worker — Durable Object
 *
 * Extends DurableObject to expose all 21 SkyFi MCP tools via
 * WebStandardStreamableHTTPServerTransport from the MCP SDK.
 * Each tool validates input with zod, then proxies to the Python service
 * via fetch.
 *
 * Phase 4 additions:
 *   - SQLite-backed notification queue (this.ctx.storage.sql)
 *   - Internal webhook dispatch endpoint (POST /_internal/notify)
 *   - check_notifications reads from local DO queue instead of proxying
 */

import { DurableObject } from "cloudflare:workers";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import { z } from "zod";

import type { Env, Props, StoredNotification, WebhookPayload } from "./types.js";
import { proxyToolCall } from "./proxy.js";
import { fetchThumbnails, type FetchedThumbnail } from "./thumbnails.js";

const DEFAULT_WEBHOOK_URL = "https://skyfi-mcp.quan-le-530.workers.dev/webhook";

// ---------------------------------------------------------------------------
// Thumbnail data-URI injection
// ---------------------------------------------------------------------------

/**
 * Embed base64 data URIs into result objects and strip external thumbnail_url.
 * Mutates `resultData` in place. Works for both search (list) and detail
 * (single result) payloads.
 */
function injectThumbnailDataUris(
  resultData: Record<string, unknown>,
  thumbnails: Map<string, FetchedThumbnail>,
): void {
  const results = resultData.results;
  if (Array.isArray(results)) {
    for (const item of results) {
      const aid = item.archive_id as string | undefined;
      if (aid) {
        const thumb = thumbnails.get(aid);
        if (thumb) {
          item.thumbnail_data_uri = `data:${thumb.mimeType};base64,${thumb.base64}`;
        }
      }
      delete item.thumbnail_url;
    }
  } else {
    const aid = resultData.archive_id as string | undefined;
    if (aid) {
      const thumb = thumbnails.get(aid);
      if (thumb) {
        resultData.thumbnail_data_uri = `data:${thumb.mimeType};base64,${thumb.base64}`;
      }
    }
    delete resultData.thumbnail_url;
  }
}

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
// SkyFiMCP Durable Object
// ---------------------------------------------------------------------------

export class SkyFiMCP extends DurableObject<Env> {
  server = new McpServer({ name: "skyfi_mcp", version: "1.0.0" });
  private transport: WebStandardStreamableHTTPServerTransport | null = null;
  private props: Props | undefined;
  private initialized = false;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.initNotificationsTable();
  }

  // -------------------------------------------------------------------------
  // SQLite notification queue — schema init
  // -------------------------------------------------------------------------

  /** Ensure the notifications table exists (idempotent). */
  private initNotificationsTable(): void {
    this.ctx.storage.sql.exec(`
      CREATE TABLE IF NOT EXISTS notifications (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        monitor_id TEXT NOT NULL DEFAULT '',
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL,
        read INTEGER DEFAULT 0
      )
    `);
  }

  // -------------------------------------------------------------------------
  // Notification queue — internal methods
  // -------------------------------------------------------------------------

  /** Store a webhook notification in the local SQLite queue. */
  private storeNotification(notification: {
    id: string;
    type: string;
    monitorId: string;
    payload: Record<string, unknown>;
  }): void {
    this.ctx.storage.sql.exec(
      `INSERT OR REPLACE INTO notifications (id, type, monitor_id, payload, created_at, read)
       VALUES (?, ?, ?, ?, ?, 0)`,
      notification.id,
      notification.type,
      notification.monitorId,
      JSON.stringify(notification.payload),
      new Date().toISOString(),
    );
  }

  /** Read unread notifications, optionally limited. */
  private getUnreadNotifications(limit: number = 50): StoredNotification[] {
    return this.ctx.storage.sql
      .exec<StoredNotification>(
        `SELECT id, type, monitor_id, payload, created_at, read
         FROM notifications
         WHERE read = 0
         ORDER BY created_at DESC
         LIMIT ?`,
        limit,
      )
      .toArray();
  }

  /** Mark specific notifications as read. */
  private markNotificationsRead(ids: string[]): number {
    if (ids.length === 0) return 0;
    // Build placeholders
    const placeholders = ids.map(() => "?").join(",");
    const result = this.ctx.storage.sql.exec(
      `UPDATE notifications SET read = 1 WHERE id IN (${placeholders})`,
      ...ids,
    );
    return result.rowsWritten;
  }

  /** Mark all unread notifications as read. */
  private markAllNotificationsRead(): number {
    const result = this.ctx.storage.sql.exec(
      `UPDATE notifications SET read = 1 WHERE read = 0`,
    );
    return result.rowsWritten;
  }

  // -------------------------------------------------------------------------
  // Fetch handler override — accept internal webhook dispatches
  // -------------------------------------------------------------------------

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);

    // Internal endpoint: receive webhook dispatches from the Worker
    if (url.pathname === "/_internal/notify" && request.method === "POST") {
      return this.handleInternalNotify(request);
    }

    // Internal endpoint: mark notifications as read
    if (url.pathname === "/_internal/mark-read" && request.method === "POST") {
      return this.handleMarkRead(request);
    }

    // Extract props from header (set by the Worker's handleMcp)
    const propsHeader = request.headers.get("X-MCP-Props");
    if (propsHeader) {
      try {
        this.props = JSON.parse(propsHeader) as Props;
      } catch {
        // Malformed header — shouldn't happen since we control both sides
      }
    }

    // Require API key
    if (!this.props?.skyfiApiKey) {
      return new Response(
        JSON.stringify({
          jsonrpc: "2.0",
          error: { code: -32000, message: "Missing API key in props" },
          id: null,
        }),
        { status: 500, headers: { "Content-Type": "application/json" } },
      );
    }

    try {
      // Lazy init: create transport, register tools, connect server
      if (!this.initialized) {
        this.transport = new WebStandardStreamableHTTPServerTransport({
          sessionIdGenerator: () => this.ctx.id.toString(),
        });
        await this.init();
        await this.server.connect(this.transport);
        this.initialized = true;
      }

      const response = await this.transport!.handleRequest(request);

      // F-2: SDK returns 200 for DELETE, spec requires 204 No Content
      if (request.method === "DELETE" && response.status === 200) {
        return new Response(null, { status: 204, headers: response.headers });
      }

      return response;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return new Response(
        JSON.stringify({
          jsonrpc: "2.0",
          error: { code: -32603, message: `Internal error: ${message}` },
          id: null,
        }),
        { status: 500, headers: { "Content-Type": "application/json" } },
      );
    }
  }

  /** Handle POST /_internal/notify — store an incoming webhook notification. */
  private async handleInternalNotify(request: Request): Promise<Response> {
    let body: WebhookPayload;
    try {
      body = (await request.json()) as WebhookPayload;
    } catch {
      return new Response(
        JSON.stringify({ error: "bad_request", message: "Invalid JSON" }),
        { status: 400, headers: { "Content-Type": "application/json" } },
      );
    }

    // Generate a unique notification ID
    const id = crypto.randomUUID();

    this.storeNotification({
      id,
      type: body.event_type ?? "unknown",
      monitorId: body.monitor_id ?? "",
      payload: body.data ?? {},
    });

    return new Response(
      JSON.stringify({ stored: true, notification_id: id }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  }

  /** Handle POST /_internal/mark-read — mark notifications as read. */
  private async handleMarkRead(request: Request): Promise<Response> {
    let body: { ids?: string[]; all?: boolean };
    try {
      body = (await request.json()) as { ids?: string[]; all?: boolean };
    } catch {
      return new Response(
        JSON.stringify({ error: "bad_request", message: "Invalid JSON" }),
        { status: 400, headers: { "Content-Type": "application/json" } },
      );
    }

    let updated: number;
    if (body.all) {
      updated = this.markAllNotificationsRead();
    } else if (body.ids && Array.isArray(body.ids)) {
      updated = this.markNotificationsRead(body.ids);
    } else {
      return new Response(
        JSON.stringify({ error: "bad_request", message: "Provide ids array or all:true" }),
        { status: 400, headers: { "Content-Type": "application/json" } },
      );
    }

    return new Response(
      JSON.stringify({ marked_read: updated }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  }

  // -------------------------------------------------------------------------
  // MCP tool registration
  // -------------------------------------------------------------------------

  async init() {
    // Initialize the notifications table on first use
    this.initNotificationsTable();

    // Convenience: proxy a tool call to the Python service
    const proxy = async (
      toolName: string,
      input: Record<string, unknown>,
    ) => {
      const result = await proxyToolCall(this.env.SKYFI_API_BASE_URL, {
        toolName,
        input,
        apiKey: this.props!.skyfiApiKey,
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
        include_thumbnails: z.boolean().default(true).describe("Embed thumbnail images in response"),
      },
      READ_ONLY,
      async (input) => {
        const { include_thumbnails, ...proxyInput } = input;
        const result = await proxyToolCall(this.env.SKYFI_API_BASE_URL, {
          toolName: "search_archive",
          input: proxyInput,
          apiKey: this.props!.skyfiApiKey,
        });

        const resultData = result.data as Record<string, unknown>;
        let thumbnails = new Map<string, FetchedThumbnail>();

        if (result.ok && include_thumbnails !== false) {
          const searchResults = resultData as {
            results?: Array<{ archive_id: string; thumbnail_url?: string }>;
          };
          const thumbUrls = (searchResults.results ?? [])
            .filter((r): r is { archive_id: string; thumbnail_url: string } => !!r.thumbnail_url)
            .map((r) => ({ archiveId: r.archive_id, url: r.thumbnail_url }));

          if (thumbUrls.length > 0) {
            thumbnails = await fetchThumbnails(thumbUrls);
          }
        }

        // Embed data URIs and strip external thumbnail_url from all results
        if (result.ok) {
          injectThumbnailDataUris(resultData, thumbnails);
        }

        const content: Array<
          | { type: "text"; text: string }
          | { type: "image"; data: string; mimeType: string }
        > = [{ type: "text", text: JSON.stringify(resultData) }];

        // Keep Image content blocks for Claude's vision model
        for (const [, thumb] of thumbnails) {
          content.push({ type: "image", data: thumb.base64, mimeType: thumb.mimeType });
        }

        return { content, isError: !result.ok };
      },
    );

    this.server.tool(
      "get_archive_details",
      "Get detailed metadata for a specific archive image.",
      {
        archive_id: z.string().describe("Unique archive image identifier"),
        include_thumbnails: z.boolean().default(true).describe("Embed thumbnail image in response"),
      },
      READ_ONLY,
      async (input) => {
        const { include_thumbnails, ...proxyInput } = input;
        const result = await proxyToolCall(this.env.SKYFI_API_BASE_URL, {
          toolName: "get_archive_details",
          input: proxyInput,
          apiKey: this.props!.skyfiApiKey,
        });

        const resultData = result.data as Record<string, unknown>;
        let thumbnails = new Map<string, FetchedThumbnail>();

        if (result.ok && include_thumbnails !== false) {
          const details = resultData as { thumbnail_url?: string; archive_id?: string };
          if (details.thumbnail_url && details.archive_id) {
            thumbnails = await fetchThumbnails(
              [{ archiveId: details.archive_id, url: details.thumbnail_url }],
              1,
            );
          }
        }

        // Embed data URI and strip external thumbnail_url
        if (result.ok) {
          injectThumbnailDataUris(resultData, thumbnails);
        }

        const content: Array<
          | { type: "text"; text: string }
          | { type: "image"; data: string; mimeType: string }
        > = [{ type: "text", text: JSON.stringify(resultData) }];

        // Keep Image content block for Claude's vision model
        for (const [, thumb] of thumbnails) {
          content.push({ type: "image", data: thumb.base64, mimeType: thumb.mimeType });
        }

        return { content, isError: !result.ok };
      },
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
      READ_ONLY,
      async (input) => proxy("explore_providers", input),
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
      READ_ONLY,
      async (input) => proxy("estimate_archive_price", input),
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
      READ_ONLY_NON_IDEMPOTENT,
      async (input) => proxy("get_tasking_quote", input),
    );

    this.server.tool(
      "analyze_feasibility",
      "Analyze feasibility of capturing new imagery over an area.",
      {
        location: LocationInputSchema,
        time_window: DateRangeSchema.optional(),
        resolution: z.number().optional().describe("Target resolution in meters"),
      },
      READ_ONLY_NON_IDEMPOTENT,
      async (input) => proxy("analyze_feasibility", input),
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
      READ_ONLY,
      async (input) => proxy("compare_pricing", input),
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
        webhook_url: z.string().optional().describe("Webhook URL for order status notifications"),
      },
      DESTRUCTIVE,
      async (input) => proxy("place_archive_order", { ...input, webhook_url: input.webhook_url ?? DEFAULT_WEBHOOK_URL }),
    );

    this.server.tool(
      "place_tasking_order",
      "Place a tasking order for new satellite imagery capture. Requires location, capture window, product type, and resolution. Call with confirmed=false first to review, then confirmed=true to execute.",
      {
        location: LocationInputSchema,
        window_start: z.string().describe("Capture window start (ISO 8601)"),
        window_end: z.string().describe("Capture window end (ISO 8601)"),
        product_type: z.string().default("DAY").describe("Product type (e.g. DAY, NIGHT)"),
        resolution: z.string().default("HIGH").describe("Resolution level (e.g. HIGH, VERY HIGH)"),
        confirmed: z
          .boolean()
          .default(false)
          .describe("Must be true to execute the order"),
        webhook_url: z.string().optional().describe("Webhook URL for order status notifications"),
      },
      DESTRUCTIVE,
      async (input) => proxy("place_tasking_order", { ...input, webhook_url: input.webhook_url ?? DEFAULT_WEBHOOK_URL }),
    );

    this.server.tool(
      "get_order_status",
      "Check the current status and details of an existing order.",
      {
        order_id: z.string().describe("Order ID to check"),
      },
      READ_ONLY,
      async (input) => proxy("get_order_status", input),
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
      READ_ONLY,
      async (input) => proxy("list_orders", input),
    );

    this.server.tool(
      "get_order_images",
      "Retrieve download URLs for imagery delivered as part of an order.",
      {
        order_id: z.string().describe("Order ID to fetch imagery for"),
      },
      READ_ONLY,
      async (input) => proxy("get_order_images", input),
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
      CREATE,
      async (input) => proxy("setup_aoi_monitoring", { ...input, notification_url: input.notification_url ?? DEFAULT_WEBHOOK_URL }),
    );

    this.server.tool(
      "list_monitors",
      "List all active AOI monitors on your account.",
      {},
      READ_ONLY,
      async (input) => proxy("list_monitors", input),
    );

    this.server.tool(
      "delete_monitor",
      "Delete an existing AOI monitor by its ID.",
      {
        monitor_id: z.string().describe("Monitor ID to remove"),
      },
      DESTRUCTIVE,
      async (input) => proxy("delete_monitor", input),
    );

    this.server.tool(
      "get_webhook_status",
      "Check the delivery status and health of a webhook subscription.",
      {
        subscription_id: z.string().describe("Webhook subscription ID"),
      },
      READ_ONLY,
      async (input) => proxy("get_webhook_status", input),
    );

    this.server.tool(
      "check_notifications",
      "Check for unread notifications (new imagery alerts, order updates). Returns notifications from the local queue.",
      {
        limit: z.number().int().min(1).max(100).default(20).describe("Max notifications to return"),
        mark_read: z.boolean().default(false).describe("Mark returned notifications as read"),
      },
      READ_ONLY_NON_IDEMPOTENT,
      async (input) => {
        // Read from local DO SQLite queue instead of proxying to Python
        const notifications = this.getUnreadNotifications(input.limit);

        // Optionally mark as read
        if (input.mark_read && notifications.length > 0) {
          const ids = notifications.map((n) => n.id);
          this.markNotificationsRead(ids);
        }

        const result = {
          unread_count: notifications.length,
          notifications: notifications.map((n) => ({
            id: n.id,
            type: n.type,
            monitor_id: n.monitor_id || undefined,
            data: JSON.parse(n.payload),
            created_at: n.created_at,
          })),
        };

        return {
          content: [
            {
              type: "text" as const,
              text: JSON.stringify(result),
            },
          ],
        };
      },
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
      READ_ONLY,
      async (input) => proxy("geocode", input),
    );

    this.server.tool(
      "reverse_geocode",
      "Convert geographic coordinates to a human-readable address (OpenStreetMap Nominatim).",
      {
        lat: z.number().min(-90).max(90).describe("Latitude"),
        lon: z.number().min(-180).max(180).describe("Longitude"),
      },
      READ_ONLY,
      async (input) => proxy("reverse_geocode", input),
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
      READ_ONLY,
      async (input) => proxy("search_pois", input),
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
      READ_ONLY,
      async (input) => proxy("get_area_boundary", input),
    );
  }
}
