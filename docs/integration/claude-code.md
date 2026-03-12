# Using SkyFi MCP with Claude Code (CLI)

Add the SkyFi MCP server to Claude Code so you can search, price, and order satellite imagery from your terminal.

## Prerequisites

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed (`npm install -g @anthropic-ai/claude-code`)
- Python 3.11+ with [uv](https://docs.astral.sh/uv/) installed
- Your SkyFi API key from [app.skyfi.com/settings/api](https://app.skyfi.com/settings/api)

## Setup

### Option A: Project-Level Configuration (Recommended)

Create or edit `.mcp.json` in your project root:

```json
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

This makes the SkyFi tools available whenever you run `claude` inside that project directory.

### Option B: Global Configuration

Edit `~/.claude.json` to add SkyFi globally (available in all projects):

```json
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

### Option C: Add via CLI

```bash
claude mcp add skyfi -- uvx skyfi-mcp
```

Then set the environment variable in your shell before running Claude Code:

```bash
export SKYFI_API_KEY="your-api-key"
claude
```

### Option D: Use the Remote Server

If you have the remote server deployed, you can point Claude Code at it instead:

```json
{
  "mcpServers": {
    "skyfi": {
      "type": "url",
      "url": "https://skyfi-mcp.your-domain.workers.dev/mcp",
      "headers": {
        "Authorization": "Bearer your-api-key"
      }
    }
  }
}
```

## Verify Connection

After configuring, start Claude Code and check that the tools are available:

```bash
claude
# Inside the Claude Code session:
> /mcp
```

You should see `skyfi` listed with 21 tools.

## First Search

Inside a Claude Code session, type:

```
Search for satellite imagery of the Golden Gate Bridge area from the last month.
```

Claude will call the `geocode` and `search_archive` tools and present the results in your terminal.

## Example: Research Workflow

```
You: Find deforestation hotspots in Borneo. Show me available imagery
     from the last year with less than 30% cloud cover, optical sensor only.

Claude: [calls geocode("Borneo")]
        [calls search_archive with location, date_range, cloud_cover_max=30, sensor_type="optical")]
        Found 12 results. Here are the top 5:
        1. img-abc123 | Maxar | 0.5m | 2025-11-15 | 8% cloud
        2. img-def456 | Planet | 3.0m | 2025-10-22 | 15% cloud
        ...

You: How much for the Maxar image?

Claude: [calls estimate_archive_price("img-abc123")]
        Price estimate:
        - Subtotal: $120.00
        - Processing fee: $12.00
        - Total: $132.00 USD
        - Delivery: GeoTIFF, ~2-4 hours

You: Order it.

Claude: [calls place_archive_order("img-abc123", confirmed=false)]
        Order preview:
        Archive image img-abc123 from Maxar
        Total cost: $132.00 USD
        Please confirm to proceed.

You: Yes, confirm.

Claude: [calls place_archive_order("img-abc123", confirmed=true)]
        Order ord-xyz789 placed successfully.
        Estimated delivery: 2-4 hours.
```

## Environment Variable Security

Never commit your API key to version control. Use one of these approaches:

1. **Environment variable** (recommended for local development):
   ```bash
   export SKYFI_API_KEY="sk-..."
   ```

2. **direnv** (`.envrc` file, gitignored):
   ```bash
   export SKYFI_API_KEY="sk-..."
   ```

3. **Secret manager** (for CI/CD):
   ```bash
   SKYFI_API_KEY=$(aws secretsmanager get-secret-value --secret-id skyfi-api-key --query SecretString --output text)
   ```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `SKYFI_API_KEY is not set` | Add the env var to your MCP config or export it in your shell |
| `uvx: command not found` | Install uv: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Tools not appearing | Run `/mcp` to check server status; restart Claude Code |
| Connection timeout | The local server runs via stdio -- ensure `uvx skyfi-mcp` starts without errors |
