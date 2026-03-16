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

export interface FetchedThumbnail {
  base64: string;
  mimeType: string;
}

/**
 * Fetch thumbnails in parallel with per-image timeouts.
 *
 * @param urls      Array of { archiveId, url } to fetch.
 * @param maxCount  Maximum number of thumbnails to fetch (default 5).
 * @param timeoutMs Per-image timeout in milliseconds (default 5000).
 * @returns Map of archiveId -> FetchedThumbnail. Failed fetches are omitted.
 */
export async function fetchThumbnails(
  urls: ThumbnailRequest[],
  maxCount: number = 5,
  timeoutMs: number = 5000,
): Promise<Map<string, FetchedThumbnail>> {
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
        const mimeType = detectMimeType(new Uint8Array(buffer));
        return { archiveId, base64, mimeType };
      } catch {
        // Timeout, network error, etc. — silently omit
        return null;
      } finally {
        clearTimeout(timer);
      }
    }),
  );

  const thumbnails = new Map<string, FetchedThumbnail>();
  for (const result of results) {
    if (result.status === "fulfilled" && result.value) {
      thumbnails.set(result.value.archiveId, {
        base64: result.value.base64,
        mimeType: result.value.mimeType,
      });
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

/** Detect image MIME type from magic bytes. Defaults to image/png. */
function detectMimeType(bytes: Uint8Array): string {
  if (bytes[0] === 0xff && bytes[1] === 0xd8) return "image/jpeg";
  if (
    bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e &&
    bytes[3] === 0x47 && bytes[4] === 0x0d && bytes[5] === 0x0a &&
    bytes[6] === 0x1a && bytes[7] === 0x0a
  ) return "image/png";
  if (
    bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 &&
    bytes[3] === 0x46 && bytes[8] === 0x57 && bytes[9] === 0x45 &&
    bytes[10] === 0x42 && bytes[11] === 0x50
  ) return "image/webp";
  if (bytes[0] === 0x47 && bytes[1] === 0x49 && bytes[2] === 0x46) return "image/gif";
  return "image/png";
}
