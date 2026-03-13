"""
SkyFi LangGraph Research Agent

An LLM-powered satellite imagery research agent built with LangGraph and MCP.

Connects to the SkyFi MCP server for access to 21 geospatial tools, uses an
LLM for natural language understanding and autonomous tool selection, and
provides human-in-the-loop confirmation for ordering actions.

Requirements:
    pip install -r requirements-langgraph.txt

Usage:
    # Interactive mode
    python langgraph_agent.py

    # Single query
    python langgraph_agent.py "Find recent imagery of the Suez Canal"

    # Use OpenAI instead of Anthropic
    python langgraph_agent.py --provider openai

    # Connect to remote server instead of local stdio
    python langgraph_agent.py --remote https://skyfi-mcp.example.com/mcp
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.prebuilt import create_react_agent
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ORDERING_TOOLS = {"place_archive_order", "place_tasking_order"}

SYSTEM_PROMPT = """\
You are the SkyFi Geospatial Research Agent, an expert at finding, analyzing, \
and ordering satellite imagery.

Your tools span five categories:
- Search & Discovery: geocode, search_archive, get_archive_details, explore_providers
- Pricing: estimate_archive_price, get_tasking_quote, analyze_feasibility, compare_pricing
- Orders: place_archive_order, place_tasking_order, get_order_status, list_orders, get_order_images
- Monitoring: setup_aoi_monitoring, list_monitors, delete_monitor, get_webhook_status, check_notifications
- Geospatial: reverse_geocode, search_pois, get_area_boundary

Guidelines:
- Geocode locations before searching.
- Present results with key metrics (resolution, cloud cover, capture date, price).
- Estimate prices before suggesting purchases.
- Be concise but thorough.

Ordering Safety (CRITICAL):
- Call ordering tools with confirmed=false FIRST to get a price preview.
- Present the preview clearly to the user.
- Only call with confirmed=true AFTER explicit user approval.
"""


# ---------------------------------------------------------------------------
# Tool confirmation wrapper
# ---------------------------------------------------------------------------


def add_order_confirmation(tool: Any, console: Console) -> Any:
    """Wrap an ordering tool to require interactive user confirmation.

    When the LLM calls an ordering tool with ``confirmed=True``, this
    wrapper intercepts the call, displays the order details, and asks
    the user to confirm before proceeding.  Preview calls
    (``confirmed=False``) pass through without interruption.
    """
    from langchain_core.tools import StructuredTool

    original_coroutine = tool.coroutine

    async def confirmed_coroutine(**kwargs: Any) -> Any:
        if kwargs.get("confirmed") is True:
            # Show order details
            detail_lines = []
            for k, v in kwargs.items():
                if k != "confirmed":
                    detail_lines.append(f"  [bold]{k}:[/bold] {v}")
            console.print()
            console.print(
                Panel(
                    "\n".join(detail_lines) or "  (no additional details)",
                    title="[yellow bold]Order Confirmation Required[/yellow bold]",
                    subtitle=f"[dim]{tool.name}[/dim]",
                    border_style="yellow",
                )
            )

            # Ask for confirmation in a thread to avoid blocking the event loop
            proceed = await asyncio.to_thread(
                Confirm.ask,
                "  [bold]Proceed with this order?[/bold]",
                console=console,
            )
            if not proceed:
                return json.dumps(
                    {
                        "status": "cancelled",
                        "message": "Order cancelled by user.",
                    }
                )

        return await original_coroutine(**kwargs)

    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        coroutine=confirmed_coroutine,
        response_format="content",
    )


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def _extract_text(content: Any) -> str:
    """Extract plain text from an AI message's content.

    Anthropic models return content as a list of blocks
    (e.g. [{"type": "text", "text": "..."}]) while OpenAI returns a string.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content) if content else ""


def display_tool_call(msg: AIMessage, console: Console) -> None:
    """Render tool calls from an AI message."""
    for tc in msg.tool_calls:
        args_str = json.dumps(tc["args"], indent=2, default=str)
        console.print(
            Panel(
                f"[dim]{args_str}[/dim]",
                title=f"[cyan bold]{tc['name']}[/cyan bold]",
                border_style="cyan",
                padding=(0, 1),
            )
        )


def display_tool_result(msg: ToolMessage, console: Console) -> None:
    """Render a tool result, truncating long output."""
    try:
        data = (
            json.loads(msg.content)
            if isinstance(msg.content, str)
            else msg.content
        )
        text = json.dumps(data, indent=2, default=str)
    except (json.JSONDecodeError, TypeError):
        text = str(msg.content)

    if len(text) > 1500:
        text = text[:1500] + "\n  ... (truncated)"

    console.print(
        Panel(
            f"[dim]{text}[/dim]",
            title=f"[green]{msg.name} result[/green]",
            border_style="green",
            padding=(0, 1),
        )
    )


def display_ai_text(msg: AIMessage, console: Console) -> None:
    """Render the agent's text response as Markdown."""
    text = _extract_text(msg.content)
    if text and not msg.tool_calls:
        console.print()
        console.print(
            Panel(Markdown(text), border_style="blue", padding=(1, 2))
        )


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------


def create_llm(provider: str) -> Any:
    """Create a LangChain chat model."""
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model="claude-sonnet-4-20250514")
    elif provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model="gpt-4o")
    else:
        raise ValueError(
            f"Unsupported LLM provider: {provider!r}. Use 'anthropic' or 'openai'."
        )


# ---------------------------------------------------------------------------
# MCP connection helpers
# ---------------------------------------------------------------------------


@asynccontextmanager
async def connect_stdio() -> AsyncIterator[ClientSession]:
    """Connect to the SkyFi MCP server via stdio."""
    api_key = os.environ.get("SKYFI_API_KEY", "")

    # Resolve the repo root (two levels up from packages/demo/)
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    server_script = os.path.join(repo_root, "packages", "server", "local", "server.py")
    venv_python = os.path.join(repo_root, ".venv", "bin", "python")

    if os.path.exists(server_script) and os.path.exists(venv_python):
        # Local development: run the server module directly from the workspace
        params = StdioServerParameters(
            command=venv_python,
            args=[server_script],
            env={
                "SKYFI_API_KEY": api_key,
                "SKYFI_API_BASE_URL": os.environ.get("SKYFI_API_BASE_URL", ""),
                "SKYFI_AUTH_HEADER": os.environ.get("SKYFI_AUTH_HEADER", ""),
                "PYTHONPATH": os.pathsep.join([
                    repo_root,
                    os.path.join(repo_root, "packages", "core"),
                ]),
            },
        )
    else:
        # Published package: use uvx
        params = StdioServerParameters(
            command="uvx",
            args=["skyfi-mcp"],
            env={"SKYFI_API_KEY": api_key, "PATH": os.environ.get("PATH", "")},
        )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


@asynccontextmanager
async def connect_remote(url: str) -> AsyncIterator[ClientSession]:
    """Connect to the SkyFi MCP server via Streamable HTTP (remote)."""
    from mcp.client.streamable_http import streamablehttp_client

    api_key = os.environ.get("SKYFI_API_KEY", "")
    async with streamablehttp_client(
        url=url,
        headers={"Authorization": f"Bearer {api_key}"},
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


# ---------------------------------------------------------------------------
# Agent runner
# ---------------------------------------------------------------------------


async def run_query(
    agent: Any, messages: list, console: Console
) -> list:
    """Run one agent turn, display results as they stream.

    Returns the full message list (input + new messages) for multi-turn use.
    """
    new_messages: list = []

    async for chunk in agent.astream(
        {"messages": messages}, stream_mode="updates"
    ):
        for _node_name, node_output in chunk.items():
            for msg in node_output.get("messages", []):
                new_messages.append(msg)

                if isinstance(msg, AIMessage):
                    text = _extract_text(msg.content)
                    # Show thinking text if present alongside tool calls
                    if text and msg.tool_calls:
                        console.print(f"\n[dim italic]{text}[/dim italic]")
                    if msg.tool_calls:
                        display_tool_call(msg, console)
                    elif text:
                        display_ai_text(msg, console)

                elif isinstance(msg, ToolMessage):
                    display_tool_result(msg, console)

    return messages + new_messages


async def interactive_mode(agent: Any, console: Console) -> None:
    """Run a multi-turn interactive conversation."""
    console.print(
        Panel(
            "[bold]SkyFi Geospatial Research Agent[/bold]\n\n"
            "Ask questions about satellite imagery for any location.\n"
            "Type [bold]quit[/bold] to exit.\n\n"
            "[dim]Examples:[/dim]\n"
            "  - Find recent high-res imagery of the Suez Canal\n"
            "  - Compare satellite providers for Borneo\n"
            "  - What imagery is available over Yellowstone from the last 3 months?\n"
            "  - Check the status of my recent orders",
            border_style="blue",
        )
    )

    messages: list = []

    while True:
        console.print()
        try:
            question = (
                await asyncio.to_thread(
                    console.input, "[bold green]You:[/bold green] "
                )
            ).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nGoodbye!")
            break

        if not question:
            continue
        if question.lower() in ("quit", "exit", "q"):
            console.print("Goodbye!")
            break

        messages.append(HumanMessage(content=question))

        try:
            messages = await run_query(agent, messages, console)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]")
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]")
            console.print("[dim]Try again with a different question.[/dim]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SkyFi LangGraph Research Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            '  python langgraph_agent.py "Find imagery of the Suez Canal"\n'
            "  python langgraph_agent.py --provider openai\n"
            "  python langgraph_agent.py --remote https://skyfi-mcp.example.com/mcp\n"
        ),
    )
    parser.add_argument(
        "query",
        nargs="*",
        help="Research question (omit for interactive mode)",
    )
    parser.add_argument(
        "--provider",
        choices=["anthropic", "openai"],
        default=None,
        help="LLM provider (default: auto-detect from available API keys)",
    )
    parser.add_argument(
        "--remote",
        metavar="URL",
        help="Connect to a remote MCP server URL instead of local stdio",
    )
    return parser.parse_args()


def detect_provider() -> str:
    """Auto-detect LLM provider from available API keys."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    print("Error: No LLM API key found.")
    print("Set ANTHROPIC_API_KEY or OPENAI_API_KEY in your environment.")
    sys.exit(1)


async def main() -> None:
    args = parse_args()
    console = Console()

    if not os.environ.get("SKYFI_API_KEY"):
        console.print("[red bold]Error:[/red bold] SKYFI_API_KEY is not set.")
        console.print("Get your key at https://app.skyfi.com/settings/api")
        console.print()
        console.print('  export SKYFI_API_KEY="your-key"')
        sys.exit(1)

    provider = args.provider or detect_provider()

    # Connect to MCP server
    if args.remote:
        connect = connect_remote(args.remote)
        console.print(f"Connecting to remote MCP server ({args.remote})...")
    else:
        connect = connect_stdio()
        console.print("Connecting to SkyFi MCP server (local stdio)...")

    async with connect as session:
        # Load tools
        tools = await load_mcp_tools(session)
        console.print(f"Loaded [bold]{len(tools)}[/bold] tools")

        # Enable graceful error handling and wrap ordering tools
        for i, tool in enumerate(tools):
            tool.handle_tool_error = True
            if tool.name in ORDERING_TOOLS:
                tools[i] = add_order_confirmation(tool, console)

        # Create agent
        llm = create_llm(provider)
        agent = create_react_agent(llm, tools, prompt=SYSTEM_PROMPT)
        console.print(
            f"Agent ready ([bold]{provider}[/bold])\n"
        )

        # Run
        if args.query:
            question = " ".join(args.query)
            messages = [HumanMessage(content=question)]
            await run_query(agent, messages, console)
        else:
            await interactive_mode(agent, console)


if __name__ == "__main__":
    asyncio.run(main())
