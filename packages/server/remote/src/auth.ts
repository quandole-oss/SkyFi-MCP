/**
 * SkyFi MCP Worker — OAuth / Auth helpers
 *
 * Provides an OAuthProvider that:
 *   1. Stores the user's SkyFi API key in the access-token claims during
 *      the OAuth 2.1 authorization flow (browser clients).
 *   2. Offers a /token endpoint for headless API clients that exchange
 *      their SkyFi API key for a short-lived JWT.
 *
 * Per-user secrets (API key) come from the request/token, NOT Worker secrets.
 */

import type { Env, Props } from "./types.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Shape of the claims object embedded in the access token. */
export interface TokenClaims {
  skyfiApiKey: string;
}

// ---------------------------------------------------------------------------
// Props extraction
// ---------------------------------------------------------------------------

/**
 * Build the Props object that McpAgent receives on every connection.
 *
 * The API key can arrive via:
 *   - OAuth access-token claims (browser flow)
 *   - Authorization: Bearer <key> header (headless)
 *   - X-Skyfi-Api-Key header (headless alternative)
 */
export function extractProps(request: Request): Props | null {
  // Try Authorization header first
  const authHeader = request.headers.get("Authorization");
  if (authHeader) {
    const match = authHeader.match(/^Bearer\s+(.+)$/i);
    if (match?.[1]) {
      return { skyfiApiKey: match[1] };
    }
  }

  // Try custom header
  const customKey = request.headers.get("X-Skyfi-Api-Key");
  if (customKey) {
    return { skyfiApiKey: customKey };
  }

  return null;
}

// ---------------------------------------------------------------------------
// Headless /token endpoint
// ---------------------------------------------------------------------------

/**
 * Handle POST /token — headless clients exchange their SkyFi API key for
 * a confirmation that the key is accepted.  In a production deployment
 * this would mint a JWT; for now we echo back a simple token envelope so
 * that clients can proceed to /mcp with the same key in the Authorization
 * header.
 *
 * Request body: { "api_key": "sk-..." }
 * Response: { "access_token": "<key>", "token_type": "bearer" }
 */
export async function handleTokenRequest(request: Request): Promise<Response> {
  if (request.method !== "POST") {
    return new Response(
      JSON.stringify({ error: "method_not_allowed", message: "POST required" }),
      { status: 405, headers: { "Content-Type": "application/json" } },
    );
  }

  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return new Response(
      JSON.stringify({ error: "invalid_request", message: "Invalid JSON body" }),
      { status: 400, headers: { "Content-Type": "application/json" } },
    );
  }

  const apiKey = body.api_key;
  if (typeof apiKey !== "string" || !apiKey) {
    return new Response(
      JSON.stringify({
        error: "invalid_request",
        message: "Missing or empty api_key field",
      }),
      { status: 400, headers: { "Content-Type": "application/json" } },
    );
  }

  // In production this would validate the key against SkyFi and mint a JWT.
  // For now, we return the key as the bearer token so that subsequent
  // requests to /mcp can pass it via the Authorization header.
  return new Response(
    JSON.stringify({
      access_token: apiKey,
      token_type: "bearer",
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}
