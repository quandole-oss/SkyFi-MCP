/**
 * SkyFi MCP Worker — OAuth / Auth helpers
 *
 * Provides:
 *   1. A /token endpoint where headless clients exchange a SkyFi API key
 *      for a short-lived JWT (signed with HMAC-SHA256 via Web Crypto).
 *   2. Token validation middleware that verifies JWT signatures, checks
 *      expiry, and extracts claims.
 *   3. Props extraction from Authorization headers.
 *
 * Per-user secrets (API key) come from the request/token, NOT Worker secrets.
 */

import type { Env, JWTPayload, Props } from "./types.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Token lifetime: 1 hour in seconds. */
const TOKEN_EXPIRY_SECONDS = 3600;

/** SkyFi API endpoint used to validate an API key. */
const SKYFI_VALIDATE_PATH = "/v1/user/profile";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Shape of the claims object embedded in the access token. */
export interface TokenClaims {
  skyfiApiKey: string;
}

// ---------------------------------------------------------------------------
// Internal: Web Crypto helpers (HMAC-SHA256)
// ---------------------------------------------------------------------------

/** Import a secret string as an HMAC-SHA256 CryptoKey. */
async function getSigningKey(secret: string): Promise<CryptoKey> {
  const encoder = new TextEncoder();
  return crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

/** Base64url-encode a Uint8Array (no padding). */
function base64urlEncode(data: Uint8Array): string {
  let binary = "";
  for (const byte of data) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/** Base64url-decode a string back to Uint8Array. */
function base64urlDecode(str: string): Uint8Array {
  // Restore standard base64
  let base64 = str.replace(/-/g, "+").replace(/_/g, "/");
  // Add padding
  while (base64.length % 4 !== 0) {
    base64 += "=";
  }
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

/** Encode a JS object as a base64url JSON string. */
function encodeSegment(obj: Record<string, unknown>): string {
  const json = JSON.stringify(obj);
  return base64urlEncode(new TextEncoder().encode(json));
}

// ---------------------------------------------------------------------------
// JWT creation & verification
// ---------------------------------------------------------------------------

/**
 * Create a signed JWT with the given payload.
 * Uses HMAC-SHA256 with the provided secret.
 */
async function createJWT(
  payload: JWTPayload,
  secret: string,
): Promise<string> {
  const header = { alg: "HS256", typ: "JWT" };
  const headerB64 = encodeSegment(header);
  const payloadB64 = encodeSegment(payload as unknown as Record<string, unknown>);
  const signingInput = `${headerB64}.${payloadB64}`;

  const key = await getSigningKey(secret);
  const signatureBuffer = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(signingInput),
  );
  const signatureB64 = base64urlEncode(new Uint8Array(signatureBuffer));

  return `${signingInput}.${signatureB64}`;
}

/**
 * Verify a JWT and return the decoded payload.
 * Returns null if the signature is invalid or the token is expired.
 */
async function verifyJWT(
  token: string,
  secret: string,
): Promise<JWTPayload | null> {
  const parts = token.split(".");
  if (parts.length !== 3) {
    return null;
  }

  const [headerB64, payloadB64, signatureB64] = parts;
  const signingInput = `${headerB64}.${payloadB64}`;

  // Verify signature
  const key = await getSigningKey(secret);
  const signatureBytes = base64urlDecode(signatureB64!);
  const valid = await crypto.subtle.verify(
    "HMAC",
    key,
    signatureBytes,
    new TextEncoder().encode(signingInput),
  );

  if (!valid) {
    return null;
  }

  // Decode payload
  let payload: JWTPayload;
  try {
    const payloadJson = new TextDecoder().decode(base64urlDecode(payloadB64!));
    payload = JSON.parse(payloadJson) as JWTPayload;
  } catch {
    return null;
  }

  // Check expiry
  const now = Math.floor(Date.now() / 1000);
  if (payload.exp && payload.exp < now) {
    return null;
  }

  return payload;
}

// ---------------------------------------------------------------------------
// SkyFi API key validation
// ---------------------------------------------------------------------------

/**
 * Validate a SkyFi API key by calling the SkyFi API.
 * Returns true if the key is valid (API returns 2xx).
 */
async function validateSkyFiApiKey(
  apiKey: string,
  baseUrl: string,
): Promise<boolean> {
  try {
    const response = await fetch(`${baseUrl}${SKYFI_VALIDATE_PATH}`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        Accept: "application/json",
      },
    });
    return response.ok;
  } catch {
    // Network errors — treat as invalid to be safe
    return false;
  }
}

// ---------------------------------------------------------------------------
// Props extraction
// ---------------------------------------------------------------------------

/**
 * Build the Props object that McpAgent receives on every connection.
 *
 * The API key can arrive via:
 *   - JWT access token (Authorization: Bearer <jwt>) — preferred
 *   - X-Skyfi-Api-Key header (headless alternative, raw key)
 *
 * When a JWT is provided, we verify it and extract the skyfiApiKey claim.
 * When a raw key is provided via X-Skyfi-Api-Key, we use it directly.
 */
export async function extractProps(
  request: Request,
  env: Env,
): Promise<Props | null> {
  // Try Authorization header first (JWT flow)
  const authHeader = request.headers.get("Authorization");
  if (authHeader) {
    const match = authHeader.match(/^Bearer\s+(.+)$/i);
    if (match?.[1]) {
      const token = match[1];

      // Try to verify as JWT first
      const payload = await verifyJWT(token, env.OAUTH_CLIENT_SECRET);
      if (payload?.skyfiApiKey) {
        return { skyfiApiKey: payload.skyfiApiKey };
      }

      // If it's not a valid JWT, treat it as a raw API key
      // (backwards compatibility for headless clients)
      return { skyfiApiKey: token };
    }
  }

  // Try custom header (raw key)
  const customKey = request.headers.get("X-Skyfi-Api-Key");
  if (customKey) {
    return { skyfiApiKey: customKey };
  }

  return null;
}

// ---------------------------------------------------------------------------
// Token validation middleware
// ---------------------------------------------------------------------------

/**
 * Validate a Bearer token from the Authorization header.
 * Returns the decoded JWT payload if valid, or null if invalid/missing.
 *
 * This is exported for use by index.ts as middleware before routing
 * to authenticated endpoints.
 */
export async function validateToken(
  request: Request,
  env: Env,
): Promise<JWTPayload | null> {
  const authHeader = request.headers.get("Authorization");
  if (!authHeader) {
    return null;
  }

  const match = authHeader.match(/^Bearer\s+(.+)$/i);
  if (!match?.[1]) {
    return null;
  }

  return verifyJWT(match[1], env.OAUTH_CLIENT_SECRET);
}

// ---------------------------------------------------------------------------
// Headless /token endpoint
// ---------------------------------------------------------------------------

/**
 * Handle POST /token — headless clients exchange their SkyFi API key for
 * a short-lived JWT signed with HMAC-SHA256.
 *
 * The handler first validates the API key against the SkyFi API. If valid,
 * it issues a JWT containing the API key in the claims.
 *
 * Request body: { "api_key": "sk-..." }
 * Response:     { "access_token": "<jwt>", "token_type": "bearer", "expires_in": 3600 }
 */
export async function handleTokenRequest(
  request: Request,
  env: Env,
): Promise<Response> {
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

  // Validate the API key against SkyFi
  const isValid = await validateSkyFiApiKey(apiKey, env.SKYFI_API_BASE_URL);
  if (!isValid) {
    return new Response(
      JSON.stringify({
        error: "invalid_api_key",
        message: "The provided SkyFi API key is invalid or expired",
      }),
      { status: 401, headers: { "Content-Type": "application/json" } },
    );
  }

  // Issue a signed JWT
  const now = Math.floor(Date.now() / 1000);
  const payload: JWTPayload = {
    skyfiApiKey: apiKey,
    iat: now,
    exp: now + TOKEN_EXPIRY_SECONDS,
  };

  const jwt = await createJWT(payload, env.OAUTH_CLIENT_SECRET);

  return new Response(
    JSON.stringify({
      access_token: jwt,
      token_type: "bearer",
      expires_in: TOKEN_EXPIRY_SECONDS,
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}
