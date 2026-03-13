/**
 * SkyFi MCP Worker — Entry point (Cloudflare Worker)
 *
 * Manual fetch handler that routes requests to the appropriate handler:
 *   /health  -> health check
 *   /token   -> headless API key exchange (issues JWT)
 *   /webhook -> webhook handler (HMAC-verified, dispatches to DO)
 *   /mcp     -> MCP agent (Streamable HTTP) via Durable Object
 *   /sse     -> MCP agent (SSE fallback) via Durable Object
 *
 * Section 3.4 Pain Point 3: Use a manual fetch handler (NOT McpAgent.serve()
 * as the sole export) so we can split MCP from other routes and inject the
 * API key as props.
 */

import type { Env, Props, WebhookPayload } from "./types.js";
import { extractProps, handleTokenRequest } from "./auth.js";
// validateToken is also exported from auth.ts for middleware use
import { rateLimitResponse } from "./rate-limit.js";

// Re-export the Durable Object class so the runtime can find it.
export { SkyFiMCP } from "./mcp-agent.js";

// ---------------------------------------------------------------------------
// CORS helpers
// ---------------------------------------------------------------------------

/** Allowed origins for CORS. Use "*" for public MCP endpoints. */
const CORS_HEADERS: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
  "Access-Control-Allow-Headers":
    "Content-Type, Authorization, Accept, X-Skyfi-Api-Key, X-Skyfi-Signature, Mcp-Session-Id, Mcp-Protocol-Version",
  "Access-Control-Expose-Headers": "Mcp-Session-Id",
  "Access-Control-Max-Age": "86400",
};

/** Return a 204 preflight response with CORS headers. */
function handleCorsPreflightRequest(): Response {
  return new Response(null, { status: 204, headers: CORS_HEADERS });
}

/** Attach CORS headers to an existing response. */
function withCors(response: Response): Response {
  const newHeaders = new Headers(response.headers);
  for (const [key, value] of Object.entries(CORS_HEADERS)) {
    newHeaders.set(key, value);
  }
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: newHeaders,
  });
}

// ---------------------------------------------------------------------------
// Health check
// ---------------------------------------------------------------------------

function handleHealth(): Response {
  return new Response(
    JSON.stringify({
      status: "ok",
      service: "skyfi-mcp",
      timestamp: new Date().toISOString(),
    }),
    {
      status: 200,
      headers: { "Content-Type": "application/json" },
    },
  );
}

// ---------------------------------------------------------------------------
// Helpers: SHA-256 hashing
// ---------------------------------------------------------------------------

/** Compute SHA-256 hex hash of a string. Used for DO key derivation. */
async function sha256Hex(input: string): Promise<string> {
  const encoder = new TextEncoder();
  const hashBuffer = await crypto.subtle.digest("SHA-256", encoder.encode(input));
  return [...new Uint8Array(hashBuffer)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// ---------------------------------------------------------------------------
// Helpers: HMAC-SHA256 webhook signature verification
// ---------------------------------------------------------------------------

/**
 * Verify an HMAC-SHA256 signature using timing-safe comparison.
 *
 * @param body     Raw request body bytes.
 * @param secret   The webhook signing secret.
 * @param received The signature from the X-Skyfi-Signature header
 *                 (may be prefixed with "sha256=").
 * @returns        True if the signature is valid.
 */
async function verifyWebhookSignature(
  body: ArrayBuffer,
  secret: string,
  received: string,
): Promise<boolean> {
  const encoder = new TextEncoder();

  // Import the signing secret as an HMAC key
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );

  // Compute the expected signature
  const expectedBuffer = await crypto.subtle.sign("HMAC", key, body);
  const expectedBytes = new Uint8Array(expectedBuffer);

  // Convert expected to hex
  const expectedHex = [...expectedBytes]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");

  // Normalize received: strip optional "sha256=" prefix, lowercase
  const receivedNormalized = received.toLowerCase().replace(/^sha256=/, "");
  const expectedNormalized = expectedHex.toLowerCase();

  // Length mismatch means different signatures — reject
  if (receivedNormalized.length !== expectedNormalized.length) {
    return false;
  }

  // Timing-safe comparison: XOR every byte of the hex strings,
  // accumulate mismatches. This avoids early-exit branches that
  // would leak timing information about correct prefix length.
  const receivedBytes = encoder.encode(receivedNormalized);
  const expectedCompareBytes = encoder.encode(expectedNormalized);

  let mismatch = 0;
  for (let i = 0; i < receivedBytes.length; i++) {
    mismatch |= receivedBytes[i]! ^ expectedCompareBytes[i]!;
  }
  return mismatch === 0;
}

// ---------------------------------------------------------------------------
// Webhook handler (HMAC-verified, dispatches to user's DO)
// ---------------------------------------------------------------------------

async function handleWebhook(request: Request, env: Env): Promise<Response> {
  if (request.method !== "POST") {
    return new Response(
      JSON.stringify({ error: "method_not_allowed", message: "POST required" }),
      { status: 405, headers: { "Content-Type": "application/json" } },
    );
  }

  // Require the signature header
  const signature = request.headers.get("X-Skyfi-Signature");
  if (!signature) {
    return new Response(
      JSON.stringify({ error: "unauthorized", message: "Missing signature" }),
      { status: 401, headers: { "Content-Type": "application/json" } },
    );
  }

  // Read body as raw bytes for HMAC verification, then parse as JSON
  const bodyBuffer = await request.arrayBuffer();

  const signatureValid = await verifyWebhookSignature(
    bodyBuffer,
    env.SKYFI_WEBHOOK_SIGNING_SECRET,
    signature,
  );

  if (!signatureValid) {
    return new Response(
      JSON.stringify({ error: "unauthorized", message: "Invalid signature" }),
      { status: 401, headers: { "Content-Type": "application/json" } },
    );
  }

  // Parse the verified body
  let payload: WebhookPayload;
  try {
    const bodyText = new TextDecoder().decode(bodyBuffer);
    payload = JSON.parse(bodyText) as WebhookPayload;
  } catch {
    return new Response(
      JSON.stringify({ error: "bad_request", message: "Invalid JSON body" }),
      { status: 400, headers: { "Content-Type": "application/json" } },
    );
  }

  // The webhook payload must include a user_id (the SHA-256 hex of the
  // user's API key) to route the notification to the correct DO instance.
  const userId = payload.user_id;
  if (!userId) {
    return new Response(
      JSON.stringify({ error: "bad_request", message: "Missing user_id in payload" }),
      { status: 400, headers: { "Content-Type": "application/json" } },
    );
  }

  // Dispatch to the user's Durable Object via the internal notify endpoint
  const doId = env.SKYFI_MCP.idFromName(userId);
  const stub = env.SKYFI_MCP.get(doId);

  const dispatchResponse = await stub.fetch(
    new Request("https://internal/_internal/notify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );

  if (!dispatchResponse.ok) {
    return new Response(
      JSON.stringify({ error: "dispatch_failed", message: "Failed to store notification" }),
      { status: 502, headers: { "Content-Type": "application/json" } },
    );
  }

  return new Response(
    JSON.stringify({ received: true }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

// ---------------------------------------------------------------------------
// MCP route — forward to Durable Object
// ---------------------------------------------------------------------------

async function handleMcp(
  request: Request,
  env: Env,
  props: Props,
): Promise<Response> {
  // For POST requests, validate Content-Type and pre-parse the JSON body
  // at the edge so malformed requests never reach the Durable Object.
  let validatedBody: string | null = null;

  if (request.method === "POST") {
    const contentType = request.headers.get("Content-Type");
    if (!contentType?.includes("application/json")) {
      return new Response(
        JSON.stringify({
          jsonrpc: "2.0",
          error: { code: -32000, message: "Unsupported Media Type: Content-Type must be application/json" },
          id: null,
        }),
        { status: 415, headers: { "Content-Type": "application/json" } },
      );
    }

    try {
      const body = await request.json();
      validatedBody = JSON.stringify(body);
    } catch {
      return new Response(
        JSON.stringify({
          jsonrpc: "2.0",
          error: { code: -32700, message: "Parse error: Invalid JSON" },
          id: null,
        }),
        { status: 400, headers: { "Content-Type": "application/json" } },
      );
    }
  }

  // Use the API key as the Durable Object ID so each user gets their own
  // session-scoped instance.  Hash it to keep the key out of the DO name.
  const hashHex = await sha256Hex(props.skyfiApiKey);

  const id = env.SKYFI_MCP.idFromName(hashHex);
  const stub = env.SKYFI_MCP.get(id);

  // Forward the request to the Durable Object.
  // The DO's fetch handler uses WebStandardStreamableHTTPServerTransport
  // to handle MCP protocol negotiation (Streamable HTTP).
  //
  // We pass the props via a custom header so the DO can pick them up
  // before the MCP session starts.
  const headers = new Headers(request.headers);
  headers.set("X-MCP-Props", JSON.stringify(props));

  const doRequest = new Request(request.url, {
    method: request.method,
    headers,
    body: validatedBody,
  });

  return stub.fetch(doRequest);
}

// ---------------------------------------------------------------------------
// In-memory sliding-window rate limiter (per-isolate)
// ---------------------------------------------------------------------------
// Lightweight rate limiter that operates within a single Worker isolate.
// Does not persist across isolate restarts but provides effective rate
// limiting at the edge without extra DO round-trips. For durable rate
// limiting, the DO storage-based checkRateLimit() from rate-limit.ts can
// be used via internal DO endpoints.

const RATE_LIMIT_WINDOW_MS = 60_000; // 1 minute
const RATE_LIMIT_MAX_REQUESTS = 60;

/** Map of userKey -> array of request timestamps in the current window. */
const rateLimitMap = new Map<string, number[]>();

interface InMemoryRateLimitResult {
  allowed: boolean;
  remaining: number;
  retryAfterSeconds: number;
}

function checkInMemoryRateLimit(userKey: string): InMemoryRateLimitResult {
  const now = Date.now();
  const windowStart = now - RATE_LIMIT_WINDOW_MS;

  let timestamps = rateLimitMap.get(userKey) ?? [];

  // Prune expired entries
  timestamps = timestamps.filter((ts) => ts > windowStart);

  if (timestamps.length >= RATE_LIMIT_MAX_REQUESTS) {
    const oldestInWindow = timestamps[0]!;
    const retryAfterMs = oldestInWindow + RATE_LIMIT_WINDOW_MS - now;
    const retryAfterSeconds = Math.ceil(retryAfterMs / 1000);

    rateLimitMap.set(userKey, timestamps);

    return {
      allowed: false,
      remaining: 0,
      retryAfterSeconds: Math.max(retryAfterSeconds, 1),
    };
  }

  timestamps.push(now);
  rateLimitMap.set(userKey, timestamps);

  return {
    allowed: true,
    remaining: RATE_LIMIT_MAX_REQUESTS - timestamps.length,
    retryAfterSeconds: 0,
  };
}

// ---------------------------------------------------------------------------
// Main fetch handler
// ---------------------------------------------------------------------------

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    // --- CORS preflight ---
    if (request.method === "OPTIONS") {
      return handleCorsPreflightRequest();
    }

    // --- Public routes (no auth required) ---

    if (path === "/health" || path === "/health/") {
      return withCors(handleHealth());
    }

    if (path === "/token" || path === "/token/") {
      return withCors(await handleTokenRequest(request, env));
    }

    if (path === "/webhook" || path === "/webhook/") {
      return withCors(await handleWebhook(request, env));
    }

    // --- MCP routes (auth required) ---

    if (path === "/mcp" || path === "/mcp/" || path === "/sse" || path === "/sse/") {
      const props = await extractProps(request, env);
      if (!props) {
        return withCors(
          new Response(
            JSON.stringify({
              error: "unauthorized",
              message:
                "SkyFi API key required. Pass it via Authorization: Bearer <jwt> " +
                "or X-Skyfi-Api-Key header.",
            }),
            { status: 401, headers: { "Content-Type": "application/json" } },
          ),
        );
      }

      // Rate limiting — keyed by hashed API key
      const userHash = await sha256Hex(props.skyfiApiKey);
      const rlResult = checkInMemoryRateLimit(userHash);
      if (!rlResult.allowed) {
        return withCors(rateLimitResponse(rlResult.retryAfterSeconds));
      }

      const response = await handleMcp(request, env, props);
      return withCors(response);
    }

    // --- Fallback ---

    return withCors(
      new Response(
        JSON.stringify({
          error: "not_found",
          message: `No handler for ${path}`,
          available_routes: ["/health", "/token", "/webhook", "/mcp", "/sse"],
        }),
        { status: 404, headers: { "Content-Type": "application/json" } },
      ),
    );
  },
};
