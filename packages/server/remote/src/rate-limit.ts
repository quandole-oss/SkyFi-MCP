/**
 * SkyFi MCP Worker — Sliding-window rate limiter
 *
 * Uses Durable Object storage to track per-user request timestamps.
 * Default: 60 requests per minute per user.
 *
 * The rate limiter is keyed by a user identifier (e.g. API key hash) and
 * stores timestamps in DO transactional storage so they survive restarts.
 */

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const DEFAULT_WINDOW_MS = 60_000; // 1 minute
const DEFAULT_MAX_REQUESTS = 60;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface RateLimitResult {
  /** Whether the request is allowed. */
  allowed: boolean;
  /** Number of requests remaining in the current window. */
  remaining: number;
  /** Seconds until the oldest request in the window expires (for Retry-After). */
  retryAfterSeconds: number;
}

// ---------------------------------------------------------------------------
// Core logic
// ---------------------------------------------------------------------------

/**
 * Check whether a request from `userKey` is within the rate limit.
 *
 * This function uses the Durable Object's transactional storage to persist
 * a sliding window of request timestamps.  Call it from the Worker's fetch
 * handler *before* processing the request.
 *
 * @param storage  The DurableObjectStorage instance (this.ctx.storage in a DO,
 *                 or obtained via stub in the Worker).
 * @param userKey  Unique per-user key (e.g. SHA-256 hex of API key).
 * @param windowMs  Window size in milliseconds (default 60 000).
 * @param maxRequests  Maximum requests allowed in the window (default 60).
 */
export async function checkRateLimit(
  storage: DurableObjectStorage,
  userKey: string,
  windowMs: number = DEFAULT_WINDOW_MS,
  maxRequests: number = DEFAULT_MAX_REQUESTS,
): Promise<RateLimitResult> {
  const storageKey = `rl:${userKey}`;
  const now = Date.now();
  const windowStart = now - windowMs;

  // Retrieve existing timestamps
  const existing = await storage.get<number[]>(storageKey);
  let timestamps = existing ?? [];

  // Prune expired entries (outside the sliding window)
  timestamps = timestamps.filter((ts) => ts > windowStart);

  if (timestamps.length >= maxRequests) {
    // Rate limit exceeded — compute when the oldest entry will expire
    const oldestInWindow = timestamps[0]!;
    const retryAfterMs = oldestInWindow + windowMs - now;
    const retryAfterSeconds = Math.ceil(retryAfterMs / 1000);

    // Persist the pruned list (drop stale entries even on rejection)
    await storage.put(storageKey, timestamps);

    return {
      allowed: false,
      remaining: 0,
      retryAfterSeconds: Math.max(retryAfterSeconds, 1),
    };
  }

  // Record this request
  timestamps.push(now);
  await storage.put(storageKey, timestamps);

  return {
    allowed: true,
    remaining: maxRequests - timestamps.length,
    retryAfterSeconds: 0,
  };
}

/**
 * Build a 429 Too Many Requests response with appropriate headers.
 */
export function rateLimitResponse(retryAfterSeconds: number): Response {
  return new Response(
    JSON.stringify({
      error: "rate_limit_exceeded",
      message: `Too many requests. Retry after ${retryAfterSeconds} second(s).`,
    }),
    {
      status: 429,
      headers: {
        "Content-Type": "application/json",
        "Retry-After": String(retryAfterSeconds),
      },
    },
  );
}
