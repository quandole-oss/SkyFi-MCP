# SkyFi MCP Server — Architecture

## Module Boundaries

```
skyfi-mcp/
├── interfaces.py          # Orchestrator-owned. Shared contracts for all agents.
├── schemas/               # Orchestrator-owned. JSON schemas for tool I/O.
│
├── packages/core/         # Agent A's domain — Python only
│   └── skyfi_mcp/
│       ├── client/        # HTTP clients (SkyFi API, OpenStreetMap)
│       ├── tools/         # MCP tool implementations
│       └── confirmation.py # Human confirmation logic
│
├── packages/server/       # Agent B's domain
│   ├── local/             # Python FastMCP stdio server
│   └── remote/            # TypeScript Cloudflare Worker
│
├── packages/demo/         # Agent C's domain
│   └── research_agent.py  # LangChain demo agent
│
└── docs/                  # Agent C's domain
    ├── integration/       # Per-client integration guides
    └── ARCHITECTURE.md    # This file (Orchestrator-owned)
```

## Dependency Directions

Dependencies flow **inward** toward the core:

```
docs/integration guides  ──►  (no code dependency)
packages/demo            ──►  packages/core (uses tools via MCP client)
packages/server/local    ──►  packages/core (imports and registers tools)
packages/server/remote   ──►  packages/core (proxies JSON-RPC to Python service)
packages/core/tools      ──►  packages/core/client (calls SkyFi/OSM APIs)
packages/core/client     ──►  interfaces.py (implements Protocol contracts)
```

**Rules:**
- `packages/core` MUST NOT depend on `packages/server` or `packages/demo`.
- `packages/server/remote` (TypeScript) communicates with `packages/core` (Python) via HTTP proxy, not direct import.
- `packages/server/local` imports `packages/core` directly as a Python dependency.
- All tool implementations MUST conform to the Protocol types in `interfaces.py`.
- All tool I/O MUST use the Pydantic models defined in `interfaces.py`.

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| MCP server name | `{service}_mcp` | `skyfi_mcp` |
| Tool names | `snake_case` (no service prefix in MCP registration — prefix in code only) | `search_archive` |
| Python modules | `snake_case` | `skyfi_mcp/tools/search.py` |
| Pydantic models | `PascalCase` with `Input`/`Output` suffix | `SearchArchiveInput`, `SearchArchiveOutput` |
| TypeScript files | `kebab-case` | `mcp-agent.ts` |
| Environment variables | `UPPER_SNAKE_CASE` | `SKYFI_API_KEY` |
| API endpoints (remote) | lowercase path | `/mcp`, `/sse`, `/webhook`, `/health` |

## Authentication Patterns

| Mode | Mechanism | Key Location |
|------|-----------|-------------|
| Local stdio | `SKYFI_API_KEY` env var | JSON config (`mcpServers.skyfi.env`) |
| Remote browser | OAuth 2.1 (`workers-oauth-provider`) | Token claims → `this.props.skyfiApiKey` |
| Remote headless | POST `/token` with API key → JWT | JWT claims → `this.props.skyfiApiKey` |

## Tool Annotations

All tools MUST include MCP tool annotations:

| Annotation | Tools |
|-----------|-------|
| `readOnlyHint: true` | `search_archive`, `get_archive_details`, `explore_providers`, `estimate_archive_price`, `get_tasking_quote`, `analyze_feasibility`, `compare_pricing`, `get_order_status`, `list_orders`, `get_order_images`, `list_monitors`, `get_webhook_status`, `check_notifications`, `geocode`, `reverse_geocode`, `search_pois`, `get_area_boundary` |
| `destructiveHint: true` | `place_archive_order`, `place_tasking_order`, `delete_monitor` |
| `idempotentHint: true` | `search_archive`, `get_archive_details`, `explore_providers`, `estimate_archive_price`, `get_order_status`, `list_orders`, `get_order_images`, `list_monitors`, `get_webhook_status`, `check_notifications`, `geocode`, `reverse_geocode`, `search_pois`, `get_area_boundary` |
| `openWorldHint: true` | All tools (they interact with external APIs) |

## Human Confirmation Flow

**This is a hard requirement. No tool may auto-confirm orders.**

1. Agent calls `place_archive_order` or `place_tasking_order` with `confirmed: false` (or omitted).
2. Tool returns `PlaceOrderOutput` with `preview` set and `confirmation` as `None`.
3. Agent presents the preview to the user.
4. User explicitly confirms.
5. Agent calls the same tool with `confirmed: true`.
6. Tool returns `PlaceOrderOutput` with `confirmation` set and `preview` as `None`.

**Implementation rule:** The tool MUST check `confirmed == True` before calling the SkyFi order API. If `confirmed` is `False` or missing, the tool MUST return a preview only.

## Error Handling

All tools MUST return structured error responses, never bare exceptions:

```python
class ToolError(BaseModel):
    code: str          # Machine-readable error code
    message: str       # Human-readable error message
    details: dict      # Additional context
```

Error codes follow this pattern:
- `VALIDATION_ERROR` — Invalid input parameters
- `NOT_FOUND` — Resource does not exist
- `AUTH_ERROR` — Authentication or authorization failure
- `RATE_LIMITED` — API rate limit exceeded
- `UPSTREAM_ERROR` — SkyFi API returned an error
- `INTERNAL_ERROR` — Unexpected server error

**Never expose credentials, API keys, or internal stack traces in error messages.**

## Testing Requirements

- **Unit tests:** >80% coverage on core tool implementations. Use mocked HTTP responses.
- **Integration tests:** Test against SkyFi open data / sandbox endpoints.
- **Transport tests:** Verify stdio round-trip and HTTP request/response.
- **Protocol tests:** MCP Inspector must report zero violations.
- **Eval tests:** Agent-level evals with LLM-judged scoring.

## Technology Stack

| Component | Technology | Package Manager |
|-----------|-----------|----------------|
| Core tools & client | Python 3.11+ | `uv` |
| Local MCP server | FastMCP (Python) | `uv` |
| Remote MCP server | Cloudflare Workers + Agents SDK (TypeScript) | `pnpm` |
| HTTP client | `httpx` (async) | — |
| Validation | Pydantic v2 | — |
| Schema validation (TS) | `zod` | — |
| OAuth (remote) | `workers-oauth-provider` | — |
| Testing | `pytest`, `pytest-asyncio`, `pytest-httpx` | — |
| Linting | `ruff`, `mypy` (Python); `eslint`, `tsc` (TS) | — |
