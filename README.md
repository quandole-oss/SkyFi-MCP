# SkyFi MCP Server

Production-grade MCP server wrapping SkyFi's satellite imagery platform API. Enables AI agents to conversationally search, price, order, and monitor satellite imagery through the Model Context Protocol.

## Features

- **20+ MCP tools** covering archive search, pricing, ordering, monitoring, and geospatial utilities
- **Dual transport**: local stdio (FastMCP/Python) and remote Streamable HTTP (Cloudflare Workers)
- **Human-in-the-loop**: mandatory user confirmation before any order placement
- **Multi-user**: OAuth 2.1 for remote deployments, API key for local
- **OpenStreetMap integration**: geocoding, POI search, and area boundary lookup

## Quickstart

### Local (stdio) — for Claude Desktop, Cursor, Claude Code

```bash
# Install
uvx skyfi-mcp

# Or add to your MCP client config:
{
  "mcpServers": {
    "skyfi": {
      "command": "uvx",
      "args": ["skyfi-mcp"],
      "env": {
        "SKYFI_API_KEY": "your-api-key"
      }
    }
  }
}
```

### Remote (Streamable HTTP) — for Claude Web, ChatGPT, multi-user

See [deployment guide](docs/integration/) for Cloudflare Workers setup.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Integration Guides](docs/integration/)

## License

MIT
