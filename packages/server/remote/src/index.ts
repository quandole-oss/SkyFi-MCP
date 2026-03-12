/**
 * SkyFi MCP Worker — Entry point (Cloudflare Worker)
 *
 * Manual fetch handler that routes requests to the appropriate handler:
 *   /health  -> health check
 *   /token   -> headless API key exchange
 *   /webhook -> webhook handler
 *   /mcp     -> MCP agent (Streamable HTTP) via Durable Object
 *   /sse     -> MCP agent (SSE fallback) via Durable Object
 *
 * Section 3.4 Pain Point 3: Use a manual fetch handler (NOT McpAgent.serve()
 * as the sole export) so we can split MCP from other routes and inject the
 * API key as props.
 */

import type { Env, Props } from "./types.js";
import { extractProps, handleTokenRequest } from "./auth.js";

// Re-export the Durable Object class so the runtime can find it.
export { SkyFiMCP } from "./mcp-agent.js";

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
// Webhook handler (placeholder — receives SkyFi push notifications)
// ---------------------------------------------------------------------------

async function handleWebhook(request: Request, env: Env): Promise<Response> {
  if (request.method !== "POST") {
    return new Response(
      JSON.stringify({ error: "method_not_allowed", message: "POST required" }),
      { status: 405, headers: { "Content-Type": "application/json" } },
    );
  }

  // Verify the webhook signing secret
  const signature = request.headers.get("X-Skyfi-Signature");
  if (!signature) {
    return new Response(
      JSON.stringify({ error: "unauthorized", message: "Missing signature" }),
      { status: 401, headers: { "Content-Type": "application/json" } },
    );
  }

  // TODO: verify HMAC signature against env.SKYFI_WEBHOOK_SIGNING_SECRET
  // For now, accept the payload and acknowledge it.

  let payload: Record<string, unknown>;
  try {
    payload = (await request.json()) as Record<string, unknown>;
  } catch {
    return new Response(
      JSON.stringify({ error: "bad_request", message: "Invalid JSON body" }),
      { status: 400, headers: { "Content-Type": "application/json" } },
    );
  }

  // TODO: dispatch the webhook event to the relevant Durable Object session
  // so connected MCP clients receive a notification.

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
  // Use the API key as the Durable Object ID so each user gets their own
  // session-scoped instance.  Hash it to keep the key out of the DO name.
  const encoder = new TextEncoder();
  const hashBuffer = await crypto.subtle.digest(
    "SHA-256",
    encoder.encode(props.skyfiApiKey),
  );
  const hashHex = [...new Uint8Array(hashBuffer)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");

  const id = env.SKYFI_MCP.idFromName(hashHex);
  const stub = env.SKYFI_MCP.get(id);

  // Forward the request to the Durable Object.
  // The DO's fetch handler (provided by McpAgent) will handle MCP
  // protocol negotiation (Streamable HTTP or SSE).
  //
  // We pass the props via a custom header so the DO can pick them up
  // before the MCP session starts.
  const headers = new Headers(request.headers);
  headers.set("X-MCP-Props", JSON.stringify(props));

  const doRequest = new Request(request.url, {
    method: request.method,
    headers,
    body: request.body,
  });

  return stub.fetch(doRequest);
}

// ---------------------------------------------------------------------------
// Main fetch handler
// ---------------------------------------------------------------------------

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    // --- Public routes (no auth required) ---

    if (path === "/health" || path === "/health/") {
      return handleHealth();
    }

    if (path === "/token" || path === "/token/") {
      return handleTokenRequest(request);
    }

    if (path === "/webhook" || path === "/webhook/") {
      return handleWebhook(request, env);
    }

    // --- MCP routes (auth required) ---

    if (path === "/mcp" || path === "/mcp/" || path === "/sse" || path === "/sse/") {
      const props = extractProps(request);
      if (!props) {
        return new Response(
          JSON.stringify({
            error: "unauthorized",
            message:
              "SkyFi API key required. Pass it via Authorization: Bearer <key> " +
              "or X-Skyfi-Api-Key header.",
          }),
          { status: 401, headers: { "Content-Type": "application/json" } },
        );
      }

      return handleMcp(request, env, props);
    }

    // --- Fallback ---

    return new Response(
      JSON.stringify({
        error: "not_found",
        message: `No handler for ${path}`,
        available_routes: ["/health", "/token", "/webhook", "/mcp", "/sse"],
      }),
      { status: 404, headers: { "Content-Type": "application/json" } },
    );
  },
};
