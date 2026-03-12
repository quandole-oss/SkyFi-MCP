"""
SkyFi Geospatial Research Agent -- Demo

A standalone Python demo agent that demonstrates the full SkyFi MCP workflow:
  1. Accepts a research question from the user
  2. Chains tools: geocode -> search_archive -> estimate_archive_price -> present findings
  3. Shows the human confirmation flow (presents price, waits for user input before confirming)
  4. Handles "no results" gracefully
  5. NEVER auto-confirms orders

Requirements:
    pip install -r requirements.txt

Usage:
    export SKYFI_API_KEY="your-api-key"
    python research_agent.py

    # Or with a direct question:
    python research_agent.py "Analyze deforestation patterns in the Amazon"
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SKYFI_API_KEY = os.environ.get("SKYFI_API_KEY", "")

SERVER_PARAMS = StdioServerParameters(
    command="uvx",
    args=["skyfi-mcp"],
    env={"SKYFI_API_KEY": SKYFI_API_KEY},
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _print_header(text: str) -> None:
    """Print a section header."""
    print()
    print("=" * 60)
    print(f"  {text}")
    print("=" * 60)


def _print_step(step: int, text: str) -> None:
    """Print a numbered step."""
    print(f"\n--- Step {step}: {text} ---")


def _format_result(result: dict[str, Any], index: int) -> str:
    """Format a single archive search result for display."""
    lines = [
        f"  {index}. Archive ID:   {result.get('archive_id', 'N/A')}",
        f"     Provider:     {result.get('provider', 'N/A')}",
        f"     Sensor:       {result.get('sensor_type', 'N/A')}",
        f"     Resolution:   {result.get('resolution', 'N/A')}m",
        f"     Captured:     {result.get('capture_date', 'N/A')}",
        f"     Cloud Cover:  {result.get('cloud_cover', 'N/A')}%",
        f"     Open Data:    {result.get('open_data', False)}",
    ]
    return "\n".join(lines)


async def call_tool(
    session: ClientSession, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Call an MCP tool and return the parsed JSON result."""
    print(f"  -> Calling tool: {name}")
    result = await session.call_tool(name, arguments=arguments)

    if not result.content:
        return {}

    text = result.content[0].text
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {"raw": text}


# ---------------------------------------------------------------------------
# Research workflow
# ---------------------------------------------------------------------------


async def run_research(session: ClientSession, question: str) -> None:
    """Execute the full research workflow for a user question.

    Flow:
        1. Geocode the location mentioned in the question
        2. Search the archive for matching imagery
        3. Estimate the price for the best result
        4. Present findings and offer to order (with confirmation)
    """
    _print_header(f"Research Question: {question}")

    # -- Step 1: Geocode ------------------------------------------------
    _print_step(1, "Geocoding location")

    # Extract a location hint from the question (simple heuristic)
    # In a real agent, an LLM would extract this. Here we use the full
    # question as the geocode query and let Nominatim do its best.
    location_hint = question
    # Try to extract text after common prepositions
    for prep in [" in ", " of ", " near ", " around ", " at "]:
        if prep in question.lower():
            location_hint = question.lower().split(prep, 1)[1].strip().rstrip("?.!")
            break

    geocode_result = await call_tool(session, "geocode", {"query": location_hint})

    results = geocode_result.get("results", [])
    if not results:
        print(f"  Could not geocode '{location_hint}'. Try a more specific location.")
        return

    best_match = results[0]
    lat = best_match["lat"]
    lon = best_match["lon"]
    display_name = best_match.get("display_name", location_hint)
    print(f"  Location: {display_name}")
    print(f"  Coordinates: {lat}, {lon}")

    # -- Step 2: Search archive -----------------------------------------
    _print_step(2, "Searching satellite imagery archive")

    # Build a search polygon around the geocoded point (approx 10km box)
    delta = 0.05  # ~5km at mid-latitudes
    search_polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [lon - delta, lat - delta],
                [lon - delta, lat + delta],
                [lon + delta, lat + delta],
                [lon + delta, lat - delta],
                [lon - delta, lat - delta],
            ]
        ],
    }

    # Search for imagery from the last 12 months
    now = datetime.now(timezone.utc)
    one_year_ago = now - timedelta(days=365)

    search_args: dict[str, Any] = {
        "location": search_polygon,
        "date_range": {
            "start": one_year_ago.isoformat(),
            "end": now.isoformat(),
        },
        "cloud_cover_max": 30,
        "sensor_type": "optical",
    }

    search_result = await call_tool(session, "search_archive", search_args)

    imagery_results = search_result.get("results", [])
    pagination = search_result.get("pagination", {})
    total_count = pagination.get("total_count", len(imagery_results))

    if not imagery_results:
        print("  No imagery found matching the search criteria.")
        print("  Suggestions:")
        print("    - Try a larger area or wider date range")
        print("    - Increase cloud_cover_max")
        print("    - Try a different sensor type (sar, multispectral)")
        return

    print(f"  Found {total_count} images. Showing top {min(len(imagery_results), 5)}:")
    print()
    for i, img in enumerate(imagery_results[:5], 1):
        print(_format_result(img, i))
        print()

    # -- Step 3: Estimate price -----------------------------------------
    best_image = imagery_results[0]
    best_id = best_image["archive_id"]

    _print_step(3, f"Estimating price for {best_id}")

    price_result = await call_tool(
        session,
        "estimate_archive_price",
        {"archive_id": best_id},
    )

    price = price_result.get("price", {})
    delivery_time = price_result.get("estimated_delivery_time", "unknown")

    print(f"  Image:          {best_id}")
    print(f"  Provider:       {best_image.get('provider', 'N/A')}")
    print(f"  Resolution:     {best_image.get('resolution', 'N/A')}m")
    print(f"  Subtotal:       ${price.get('subtotal', 0):.2f}")
    print(f"  Processing Fee: ${price.get('processing_fee', 0):.2f}")
    print(f"  Total:          ${price.get('total', 0):.2f} {price.get('currency', 'USD')}")
    print(f"  Delivery:       {delivery_time}")

    # -- Step 4: Offer to order (with confirmation) ---------------------
    _print_step(4, "Order confirmation")

    if best_image.get("open_data", False):
        print("  This image is open data (free). No purchase required.")
        print("  You can download it directly from the provider.")
        return

    print(f"  Would you like to order image {best_id}?")
    print(f"  Total cost: ${price.get('total', 0):.2f} {price.get('currency', 'USD')}")
    print()

    try:
        user_input = input("  Type 'yes' to order, or anything else to skip: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  Skipping order.")
        return

    if user_input not in ("yes", "y"):
        print("  Order skipped.")
        return

    # Step 4a: Preview the order (confirmed=false)
    print("\n  Generating order preview...")
    preview_result = await call_tool(
        session,
        "place_archive_order",
        {"archive_id": best_id, "confirmed": False},
    )

    # The result can be either a preview (when confirmed=false) or
    # a wrapper with preview/confirmation fields
    preview = preview_result.get("preview", preview_result)
    preview_msg = preview.get("message", "Order preview generated.")
    print(f"  {preview_msg}")
    print()

    try:
        confirm_input = input(
            "  Type 'CONFIRM' to finalize the purchase, or anything else to cancel: "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  Order cancelled.")
        return

    if confirm_input != "CONFIRM":
        print("  Order cancelled.")
        return

    # Step 4b: Execute the order (confirmed=true)
    print("\n  Placing order...")
    order_result = await call_tool(
        session,
        "place_archive_order",
        {"archive_id": best_id, "confirmed": True},
    )

    confirmation = order_result.get("confirmation", order_result)
    order_id = confirmation.get("order_id", "N/A")
    order_status = confirmation.get("status", "N/A")
    order_msg = confirmation.get("message", "Order placed.")

    print(f"  {order_msg}")
    print(f"  Order ID: {order_id}")
    print(f"  Status:   {order_status}")

    _print_header("Research Complete")


# ---------------------------------------------------------------------------
# Interactive mode
# ---------------------------------------------------------------------------


async def interactive_mode(session: ClientSession) -> None:
    """Run the agent in interactive mode, accepting questions from stdin."""
    _print_header("SkyFi Geospatial Research Agent")
    print("  Enter a research question about a location to search for")
    print("  satellite imagery. Type 'quit' to exit.")
    print()
    print("  Example questions:")
    print("    - Analyze deforestation patterns in the Amazon")
    print("    - Find recent imagery of the Suez Canal")
    print("    - Show me satellite photos of Yellowstone National Park")
    print("    - Search for imagery of flooding in Bangladesh")

    while True:
        print()
        try:
            question = input("Your question: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not question:
            continue
        if question.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break

        try:
            await run_research(session, question)
        except Exception as e:
            print(f"\n  Error: {e}")
            print("  Please try again with a different question.")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    """Connect to the SkyFi MCP server and run the research agent."""
    if not SKYFI_API_KEY:
        print("Error: SKYFI_API_KEY environment variable is not set.")
        print("Get your API key at https://app.skyfi.com/settings/api")
        print()
        print("Usage:")
        print("  export SKYFI_API_KEY=\"your-api-key\"")
        print("  python research_agent.py")
        sys.exit(1)

    print("Connecting to SkyFi MCP server...")

    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Verify tools are available
            tools_result = await session.list_tools()
            tool_names = [t.name for t in tools_result.tools]
            print(f"Connected. {len(tool_names)} tools available.")

            required_tools = ["geocode", "search_archive", "estimate_archive_price", "place_archive_order"]
            missing = [t for t in required_tools if t not in tool_names]
            if missing:
                print(f"Warning: Missing required tools: {missing}")

            # Check for command-line argument
            if len(sys.argv) > 1:
                question = " ".join(sys.argv[1:])
                await run_research(session, question)
            else:
                await interactive_mode(session)


if __name__ == "__main__":
    asyncio.run(main())
