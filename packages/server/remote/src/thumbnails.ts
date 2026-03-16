/**
 * SkyFi MCP Worker — Thumbnail fetcher
 *
 * Fetches satellite image thumbnails in parallel for embedding in MCP
 * responses as base64-encoded ImageContent.
 */

interface ThumbnailRequest {
  archiveId: string;
  url: string;
}

/**
 * Fetch thumbnails in parallel with per-image timeouts.
 *
 * @param urls      Array of { archiveId, url } to fetch.
 * @param maxCount  Maximum number of thumbnails to fetch (default 5).
 * @param timeoutMs Per-image timeout in milliseconds (default 5000).
 * @returns Map of archiveId -> base64-encoded image data. Failed fetches are omitted.
 */
export async function fetchThumbnails(
  urls: ThumbnailRequest[],
  maxCount: number = 5,
  timeoutMs: number = 5000,
): Promise<Map<string, string>> {
  if (urls.length === 0) {
    return new Map();
  }

  const toFetch = urls.slice(0, maxCount);

  const results = await Promise.allSettled(
    toFetch.map(async ({ archiveId, url }) => {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);

      try {
        const resp = await fetch(url, { signal: controller.signal });
        if (!resp.ok) {
          return null;
        }
        const buffer = await resp.arrayBuffer();
        const base64 = arrayBufferToBase64(buffer);
        return { archiveId, base64 };
      } catch {
        // Timeout, network error, etc. — silently omit
        return null;
      } finally {
        clearTimeout(timer);
      }
    }),
  );

  const thumbnails = new Map<string, string>();
  for (const result of results) {
    if (result.status === "fulfilled" && result.value) {
      thumbnails.set(result.value.archiveId, result.value.base64);
    }
  }
  return thumbnails;
}

/** Convert an ArrayBuffer to a base64 string. */
function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary);
}
