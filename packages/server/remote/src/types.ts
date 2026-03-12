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
