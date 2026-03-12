# Using SkyFi MCP with Claude.ai (Web Interface)

Connect the SkyFi MCP server to Claude.ai so you can search, price, and order satellite imagery directly from your browser.

## Prerequisites

- A Claude Pro, Team, or Enterprise account at [claude.ai](https://claude.ai)
- A deployed SkyFi MCP remote server (Cloudflare Workers) -- see [Architecture](../ARCHITECTURE.md)
- Your SkyFi API key from [app.skyfi.com/settings/api](https://app.skyfi.com/settings/api)

## Setup

### 1. Deploy the Remote MCP Server

The Claude.ai web interface connects to MCP servers over HTTPS using Streamable HTTP transport. You need the remote server running on Cloudflare Workers.

If you have not deployed it yet:

```bash
cd packages/server/remote
pnpm install
pnpm run deploy
```

Note the deployed URL, e.g. `https://skyfi-mcp.your-domain.workers.dev`.

### 2. Add the MCP Server in Claude.ai

1. Open [claude.ai](https://claude.ai) and sign in.
2. Click the **hamburger menu** (top left) and go to **Settings**.
3. Under **Integrations**, click **Add Integration** (or **Add MCP Server**).
4. Enter the following:
   - **Name:** SkyFi Satellite Imagery
   - **Server URL:** `https://skyfi-mcp.your-domain.workers.dev/mcp`
5. Click **Save**.

### 3. Authenticate

When you first use the SkyFi tools in a conversation, Claude.ai will redirect you to the OAuth flow if your remote server uses OAuth 2.1 (the default). Complete the sign-in to grant access.

If your remote server uses bearer-token authentication instead, set the token in the integration settings:

- **Authentication type:** Bearer Token
- **Token:** Your SkyFi API key

## First Search

Start a new conversation and ask Claude:

> Search for recent satellite imagery of San Francisco with less than 20% cloud cover.

Claude will call the `search_archive` tool with your parameters and return matching results including provider, resolution, capture date, and cloud cover for each image.

## Example Workflow

Here is a typical multi-step conversation:

1. **You:** "Find high-resolution optical imagery of the Amazon rainforest from the last 6 months."
2. Claude calls `geocode` to resolve "Amazon rainforest" to coordinates, then `search_archive` with the location and date range.
3. **You:** "How much does the first result cost?"
4. Claude calls `estimate_archive_price` with the archive ID from the search results.
5. **You:** "Order it in GeoTIFF format."
6. Claude calls `place_archive_order` with `confirmed: false` and presents the price preview.
7. **You:** "Yes, confirm the order."
8. Claude calls `place_archive_order` with `confirmed: true` and returns the order confirmation.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "MCP server unavailable" | Verify your server URL ends with `/mcp` and the Worker is deployed |
| "Authentication failed" | Re-check your API key or re-authorize via OAuth |
| Tools not appearing | Refresh the page; ensure the integration is listed under Settings > Integrations |
| Timeout errors | The remote server has a 30-second timeout; try narrowing your search area |

## Notes

- The Claude.ai web interface only supports **remote** MCP servers (HTTPS). You cannot use the local stdio server here.
- All 21 SkyFi tools are available once connected.
- Order placement always requires your explicit confirmation -- Claude will never auto-confirm purchases.
