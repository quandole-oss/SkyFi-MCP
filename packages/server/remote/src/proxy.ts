/**
 * SkyFi MCP Worker — Proxy helper
 *
 * Forwards JSON-RPC tool calls to the Python service at SKYFI_API_BASE_URL.
 */

export interface ProxyRequest {
  /** MCP tool name (e.g. "search_archive"). */
  toolName: string;
  /** Validated tool input object. */
  input: Record<string, unknown>;
  /** The end-user's SkyFi API key (from token claims). */
  apiKey: string;
}

export interface ProxyResponse {
  /** True if the upstream responded with 2xx. */
  ok: boolean;
  /** HTTP status code from upstream. */
  status: number;
  /** Parsed JSON body (or error payload). */
  data: Record<string, unknown>;
}

/**
 * Proxy a tool invocation to the Python SkyFi service.
 *
 * The Python service exposes each tool as POST /tools/{tool_name}
 * and expects the input in the JSON body with an Authorization header.
 */
export async function proxyToolCall(
  baseUrl: string,
  request: ProxyRequest,
): Promise<ProxyResponse> {
  const url = `${baseUrl}/tools/${request.toolName}`;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${request.apiKey}`,
    },
    body: JSON.stringify(request.input),
  });

  let data: Record<string, unknown>;
  try {
    data = (await res.json()) as Record<string, unknown>;
  } catch {
    data = {
      error: "UPSTREAM_ERROR",
      message: `Upstream returned non-JSON response (HTTP ${res.status})`,
    };
  }

  return { ok: res.ok, status: res.status, data };
}
