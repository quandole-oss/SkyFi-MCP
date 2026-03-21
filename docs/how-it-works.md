# How the SkyFi MCP Server Works with Claude Desktop

## What It Is

An MCP (Model Context Protocol) server that gives Claude access to the **SkyFi satellite imagery platform**. Once connected, you can conversationally search for satellite images, get pricing, place orders, set up monitoring, and do geocoding — all through natural language in Claude Desktop.

## The Setup

The project has three layers:

```
packages/
  core/       ← Python: API clients + 21 tool implementations
  server/
    local/    ← FastMCP stdio server (what Claude Desktop uses)
    remote/   ← Cloudflare Worker (for Claude.ai web)
```

**Claude Desktop connects via the `.mcp.json` config file**, which tells it to launch the local Python server:

```json
{
  "mcpServers": {
    "skyfi": {
      "command": "uv",
      "args": ["run", "--directory", "<project-path>", "skyfi-mcp"],
      "env": { "SKYFI_API_KEY": "..." }
    }
  }
}
```

When Claude Desktop starts, it spawns the Python process (`uv run skyfi-mcp`), which boots a **FastMCP stdio server**. They communicate over stdin/stdout using JSON-RPC — no HTTP, no ports, just piped I/O.

## The Flow

```
You type in Claude Desktop
  → Claude decides to call an MCP tool (e.g. "search_archive")
  → JSON-RPC message sent over stdio to the Python process
  → FastMCP routes it to the tool handler in packages/server/local/server.py
  → Handler calls the core tool logic (packages/core/skyfi_mcp/tools/)
  → Core logic uses httpx to call the SkyFi Platform API (and/or OpenStreetMap)
  → Results come back as Pydantic models, serialized to JSON
  → Response piped back to Claude over stdio
  → Claude presents results to you in natural language
```

## The 21 Tools (grouped)

| Category | Tools | What they do |
|---|---|---|
| **Search** | `search_archive`, `get_archive_details`, `explore_providers` | Find satellite imagery by location/date/sensor |
| **Pricing** | `estimate_archive_price`, `get_tasking_quote`, `analyze_feasibility`, `compare_pricing` | Get costs and check if a capture is viable |
| **Orders** | `place_archive_order`, `place_tasking_order`, `get_order_status`, `list_orders`, `get_order_images` | Buy imagery with human-in-the-loop confirmation |
| **Monitoring** | `setup_aoi_monitoring`, `list_monitors`, `delete_monitor`, `get_webhook_status`, `check_notifications` | Automated alerts for areas of interest |
| **Geo** | `geocode`, `reverse_geocode`, `search_pois`, `get_area_boundary` | Convert addresses to/from coordinates via OpenStreetMap |

## Key Design Decisions

- **Human-in-the-loop for orders**: When you say "order this image," the tool first returns a price preview with `confirmed=false`. Claude shows you the cost and asks you to confirm. Only when you say yes does it call again with `confirmed=true` to actually place the order.

- **GeoJSON to WKT conversion**: MCP uses GeoJSON for geometry, but SkyFi's API uses WKT (Well-Known Text). The `wkt.py` client handles translation transparently.

- **Embedded thumbnails**: Search results include base64-encoded image thumbnails so Claude can show you preview imagery inline.

- **Dual transport**: The same core tools power both the local stdio server (Claude Desktop/Claude Code) and the remote Cloudflare Worker (Claude.ai web, with OAuth 2.1 for multi-user auth).

## In Practice

You open Claude Desktop, and because the MCP config is in place, the SkyFi tools are available. You can say things like:

> "Find recent satellite imagery of the Port of Los Angeles from the last 30 days with less than 10% cloud cover"

Claude calls `geocode` to resolve the location, then `search_archive` with the coordinates and filters, and presents you with results including thumbnail previews — all without you touching an API directly.
