/**
 * SkyFi MCP Worker — Shared Type Definitions
 *
 * Keep this in sync with wrangler.toml [vars] and wrangler secrets.
 */

export interface Env {
  // Durable Object binding
  SKYFI_MCP: DurableObjectNamespace;

  // Vars (from wrangler.toml [vars])
  SKYFI_API_BASE_URL: string;
  ENVIRONMENT: string;

  // Secrets (from wrangler secret put)
  SKYFI_WEBHOOK_SIGNING_SECRET: string;
  OAUTH_CLIENT_SECRET: string;
}

export interface Props {
  /** The user's SkyFi API key, extracted from token claims during OAuth flow. */
  skyfiApiKey: string;
}

/** JWT payload embedded in access tokens issued by /token. */
export interface JWTPayload {
  /** The user's SkyFi API key. */
  skyfiApiKey: string;
  /** Issued-at timestamp (seconds since epoch). */
  iat: number;
  /** Expiration timestamp (seconds since epoch). */
  exp: number;
}

/** Shape of a webhook notification stored in the DO's SQLite. */
export interface StoredNotification {
  id: string;
  type: string;
  monitor_id: string;
  payload: string;
  created_at: string;
  read: number;
}

/** Incoming webhook payload from SkyFi. */
export interface WebhookPayload {
  /** Event type, e.g. "new_imagery", "order_update". */
  event_type: string;
  /** Monitor ID that triggered this notification, if applicable. */
  monitor_id?: string;
  /** User identifier — API key hash or user ID used to route to the right DO. */
  user_id: string;
  /** Arbitrary event-specific data. */
  data: Record<string, unknown>;
}
