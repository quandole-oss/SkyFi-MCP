# Contributing to SkyFi MCP Server

Thank you for your interest in contributing. This guide covers development setup, testing, code style, and PR guidelines.

## Development Setup

### Prerequisites

- **Python 3.11+** -- The core tools and local server are Python
- **Node.js 20+** -- The remote server (Cloudflare Worker) is TypeScript
- **[uv](https://docs.astral.sh/uv/)** -- Python package manager (replaces pip/venv)
- **[pnpm](https://pnpm.io/)** 9+ -- Node.js package manager for the TypeScript workspace

### Clone and Install

```bash
git clone https://github.com/your-org/skyfi-mcp.git
cd skyfi-mcp

# Python dependencies (core + dev tools)
uv sync --all-packages --dev

# TypeScript dependencies (remote server)
cd packages/server/remote
pnpm install
cd ../../..
```

### Project Structure

```
skyfi-mcp/
    interfaces.py              # Shared contracts (Orchestrator-owned)
    schemas/                   # JSON schemas for tool I/O
    packages/
        core/                  # Python: API client + tool implementations
            skyfi_mcp/
                client/        # HTTP clients (SkyFi API, OpenStreetMap)
                tools/         # MCP tool functions
                confirmation.py
            tests/
                unit/          # Unit tests (mocked HTTP)
                integration/   # Integration tests (sandbox API)
        server/
            local/             # Python FastMCP stdio server
            remote/            # TypeScript Cloudflare Worker
        demo/                  # Demo research agent
    docs/
        integration/           # Per-client integration guides
        api-reference.md       # Tool API reference
        ARCHITECTURE.md        # Architecture overview
```

## Running the Local Server

```bash
# Set your API key
export SKYFI_API_KEY="your-api-key"

# Run via uv
uv run python -m packages.server.local.server

# Or via the installed entry point
uv run skyfi-mcp
```

The server communicates over stdio (stdin/stdout) using the MCP JSON-RPC protocol. To test it interactively, use the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector uvx skyfi-mcp
```

## Running Tests

### Python Unit Tests

```bash
# Run all tests
uv run pytest packages/core/tests/ -v

# Run with coverage
uv run pytest packages/core/tests/ -v --cov=skyfi_mcp --cov-report=term-missing

# Run a specific test class
uv run pytest packages/core/tests/unit/test_tools.py::TestSearchArchive -v
```

Tests use `respx` to mock all HTTP requests. No real API calls are made during unit tests.

### TypeScript Type Checking

```bash
cd packages/server/remote
pnpm typecheck
```

## Code Style

### Python

We use **ruff** for linting and formatting, and **mypy** in strict mode for type checking.

```bash
# Lint
uv run ruff check packages/core/

# Auto-fix lint issues
uv run ruff check packages/core/ --fix

# Format
uv run ruff format packages/core/

# Type check (strict mode)
uv run mypy packages/core/skyfi_mcp/ interfaces.py --strict
```

#### Key rules

- **Line length:** 100 characters
- **Target version:** Python 3.11
- **Ruff rule sets:** E, F, I, N, W, UP, B, SIM, TCH
- **Type annotations:** Required on all public functions
- **Docstrings:** Required on all public modules, classes, and functions
- **No bare exceptions:** Always use structured error responses (see `ARCHITECTURE.md`)

### TypeScript

The remote server uses TypeScript strict mode with ESLint.

```bash
cd packages/server/remote
pnpm typecheck  # tsc --noEmit
```

## Adding a New Tool

1. **Define the interface** -- Add input/output Pydantic models to `interfaces.py` and update `schemas/tool-inputs.json` and `schemas/tool-outputs.json`.

2. **Implement the tool** -- Add the async function to the appropriate module in `packages/core/skyfi_mcp/tools/` (search, pricing, orders, monitoring, or geo).

3. **Register in the server** -- Add the `@mcp.tool()` handler in `packages/server/local/server.py` with proper annotations.

4. **Write tests** -- Add unit tests in `packages/core/tests/unit/test_tools.py` using `respx` mocks.

5. **Update documentation** -- Add the tool to `docs/api-reference.md`.

### Tool Annotations

Every tool must include MCP annotations. Use these presets:

| Preset | When to use |
|--------|-------------|
| `readOnlyHint: true, idempotentHint: true` | Pure queries (search, get, list) |
| `readOnlyHint: true, idempotentHint: false` | Queries that may return different results (quotes, feasibility) |
| `destructiveHint: true` | Operations that modify state (orders, deletes) |
| `openWorldHint: true` | All tools (they call external APIs) |

### Human Confirmation

Any tool that places an order or spends money **must** implement the two-step confirmation pattern:

1. `confirmed=false` (default) returns a price preview.
2. `confirmed=true` executes the order.

See `packages/core/skyfi_mcp/confirmation.py` for helpers.

## Pull Request Guidelines

### Before Submitting

1. **Run all checks locally:**
   ```bash
   uv run ruff check packages/core/
   uv run mypy packages/core/skyfi_mcp/ interfaces.py --strict
   uv run pytest packages/core/tests/ -v
   ```

2. **Ensure no credentials are committed.** Never commit API keys, `.env` files, or secrets.

3. **Update documentation** if you changed tool behavior or added new tools.

4. **Keep PRs focused.** One feature or fix per PR. If you need to refactor and add a feature, split into two PRs.

### PR Format

- **Title:** Short, descriptive (e.g., "Add hyperspectral sensor type support")
- **Description:** Explain what changed and why. Include:
  - Summary of changes
  - Test plan (how to verify)
  - Screenshots or sample output if applicable

### CI Checks

All PRs must pass these CI jobs before merge:

- **Python Lint & Type Check** -- `ruff check` + `mypy --strict`
- **Python Tests** -- `pytest` with all unit tests passing
- **TypeScript Lint & Type Check** -- `tsc --noEmit`

### Code Review

- All PRs require at least one approving review.
- Reviewers should check for:
  - Correctness (does it do what the PR says?)
  - Test coverage (are edge cases covered?)
  - Type safety (are all types explicit?)
  - Security (no leaked credentials, proper input validation)
  - Documentation (are public APIs documented?)

## Shared Contracts

The `interfaces.py` file and `schemas/` directory are the source of truth for all tool signatures. These files are owned by the orchestrator and should not be modified without coordination. If you need to change a tool's interface, open an issue first to discuss the change.

## License

By contributing, you agree that your contributions will be licensed under the project's MIT License.
