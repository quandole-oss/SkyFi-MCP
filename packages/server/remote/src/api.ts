/**
 * SkyFi MCP Worker — REST API handler
 *
 * Thin REST endpoints at /api/* for the web dashboard SPA.
 * Each endpoint maps to an existing MCP tool via proxyToolCall().
 * All routing logic is self-contained — index.ts delegates with a single
 * `if (path.startsWith("/api/"))` check.
 */

import { proxyToolCall } from "./proxy.js";

/**
 * Handle all /api/* requests.
 *
 * @param request  The incoming Request.
 * @param baseUrl  The SKYFI_API_BASE_URL for proxying.
 * @param path     The URL pathname (e.g. "/api/search").
 * @param apiKey   The user's SkyFi API key (from validated JWT).
 */
export async function handleApiRequest(
  request: Request,
  baseUrl: string,
  path: string,
  apiKey: string,
): Promise<Response> {
  const method = request.method;
  const url = new URL(request.url);

  // -----------------------------------------------------------------------
  // GET /api/search?location=...&date_from=...&sensor=...&cloud_max=...
  // -----------------------------------------------------------------------
  if (path === "/api/search" && method === "GET") {
    const locationParam = url.searchParams.get("location");
    if (!locationParam) {
      return jsonError("location parameter is required", 400);
    }

    const input: Record<string, unknown> = {
      location: parseLocationParam(locationParam),
    };

    const dateFrom = url.searchParams.get("date_from");
    const dateTo = url.searchParams.get("date_to");
    if (dateFrom && dateTo) {
      input.date_range = { start: dateFrom, end: dateTo };
    }

    const sensor = url.searchParams.get("sensor");
    if (sensor) input.sensor_type = sensor;

    const cloudMax = url.searchParams.get("cloud_max");
    if (cloudMax) input.cloud_cover_max = parseFloat(cloudMax);

    const openData = url.searchParams.get("open_data");
    if (openData) input.open_data = openData === "true";

    const pageToken = url.searchParams.get("page_token");
    if (pageToken) input.page_token = pageToken;

    return proxyAndRespond(baseUrl, "search_archive", input, apiKey);
  }

  // -----------------------------------------------------------------------
  // GET /api/archives/:id
  // -----------------------------------------------------------------------
  const archiveMatch = path.match(/^\/api\/archives\/([^/]+)$/);
  if (archiveMatch && method === "GET") {
    return proxyAndRespond(baseUrl, "get_archive_details", {
      archive_id: archiveMatch[1],
    }, apiKey);
  }

  // -----------------------------------------------------------------------
  // GET /api/orders?status=...&page=...
  // -----------------------------------------------------------------------
  if (path === "/api/orders" && method === "GET") {
    const input: Record<string, unknown> = {};
    const status = url.searchParams.get("status");
    if (status) input.status = status;
    const page = url.searchParams.get("page");
    if (page) input.page = parseInt(page, 10);
    return proxyAndRespond(baseUrl, "list_orders", input, apiKey);
  }

  // -----------------------------------------------------------------------
  // GET /api/orders/:id
  // -----------------------------------------------------------------------
  const orderMatch = path.match(/^\/api\/orders\/([^/]+)$/);
  if (orderMatch && method === "GET") {
    return proxyAndRespond(baseUrl, "get_order_status", {
      order_id: orderMatch[1],
    }, apiKey);
  }

  // -----------------------------------------------------------------------
  // GET /api/orders/:id/images
  // -----------------------------------------------------------------------
  const orderImagesMatch = path.match(/^\/api\/orders\/([^/]+)\/images$/);
  if (orderImagesMatch && method === "GET") {
    return proxyAndRespond(baseUrl, "get_order_images", {
      order_id: orderImagesMatch[1],
    }, apiKey);
  }

  // -----------------------------------------------------------------------
  // GET /api/monitors
  // -----------------------------------------------------------------------
  if (path === "/api/monitors" && method === "GET") {
    return proxyAndRespond(baseUrl, "list_monitors", {}, apiKey);
  }

  // -----------------------------------------------------------------------
  // POST /api/monitors
  // -----------------------------------------------------------------------
  if (path === "/api/monitors" && method === "POST") {
    const body = await parseJsonBody(request);
    if (!body) return jsonError("Invalid JSON body", 400);
    return proxyAndRespond(baseUrl, "setup_aoi_monitoring", body, apiKey);
  }

  // -----------------------------------------------------------------------
  // DELETE /api/monitors/:id
  // -----------------------------------------------------------------------
  const monitorDeleteMatch = path.match(/^\/api\/monitors\/([^/]+)$/);
  if (monitorDeleteMatch && method === "DELETE") {
    return proxyAndRespond(baseUrl, "delete_monitor", {
      monitor_id: monitorDeleteMatch[1],
    }, apiKey);
  }

  // -----------------------------------------------------------------------
  // GET /api/geocode?q=...
  // -----------------------------------------------------------------------
  if (path === "/api/geocode" && method === "GET") {
    const q = url.searchParams.get("q");
    if (!q) return jsonError("q parameter is required", 400);
    return proxyAndRespond(baseUrl, "geocode", { query: q }, apiKey);
  }

  // -----------------------------------------------------------------------
  // GET /api/pois?lat=...&lon=...&category=...&radius=...
  // -----------------------------------------------------------------------
  if (path === "/api/pois" && method === "GET") {
    const lat = url.searchParams.get("lat");
    const lon = url.searchParams.get("lon");
    if (!lat || !lon) return jsonError("lat and lon parameters are required", 400);

    const input: Record<string, unknown> = {
      location: { geometry: { type: "Point", coordinates: [parseFloat(lon), parseFloat(lat)] } },
    };
    const category = url.searchParams.get("category");
    if (category) input.category = category;
    const radius = url.searchParams.get("radius");
    if (radius) input.radius = parseFloat(radius);

    return proxyAndRespond(baseUrl, "search_pois", input, apiKey);
  }

  // -----------------------------------------------------------------------
  // GET /api/boundary?name=...
  // -----------------------------------------------------------------------
  if (path === "/api/boundary" && method === "GET") {
    const name = url.searchParams.get("name");
    if (!name) return jsonError("name parameter is required", 400);
    const input: Record<string, unknown> = { name };
    const adminLevel = url.searchParams.get("admin_level");
    if (adminLevel) input.admin_level = parseInt(adminLevel, 10);
    return proxyAndRespond(baseUrl, "get_area_boundary", input, apiKey);
  }

  // -----------------------------------------------------------------------
  // Fallback
  // -----------------------------------------------------------------------
  return jsonError(`Unknown API endpoint: ${method} ${path}`, 404);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Proxy a tool call and return the result as a JSON Response. */
async function proxyAndRespond(
  baseUrl: string,
  toolName: string,
  input: Record<string, unknown>,
  apiKey: string,
): Promise<Response> {
  const result = await proxyToolCall(baseUrl, { toolName, input, apiKey });
  return new Response(JSON.stringify(result.data), {
    status: result.ok ? 200 : result.status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Parse a location query parameter — supports "lat,lon" or JSON. */
function parseLocationParam(param: string): Record<string, unknown> {
  // Try "lat,lon" shorthand
  const latLon = param.match(/^(-?\d+\.?\d*),\s*(-?\d+\.?\d*)$/);
  if (latLon) {
    return {
      geometry: {
        type: "Point",
        coordinates: [parseFloat(latLon[2]!), parseFloat(latLon[1]!)],
      },
    };
  }
  // Try JSON
  try {
    return JSON.parse(param) as Record<string, unknown>;
  } catch {
    // Treat as address string
    return { address: param };
  }
}

/** Parse JSON request body, return null on failure. */
async function parseJsonBody(request: Request): Promise<Record<string, unknown> | null> {
  try {
    return (await request.json()) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/** Create a JSON error response. */
function jsonError(message: string, status: number): Response {
  return new Response(
    JSON.stringify({ error: status >= 500 ? "server_error" : "bad_request", message }),
    { status, headers: { "Content-Type": "application/json" } },
  );
}
