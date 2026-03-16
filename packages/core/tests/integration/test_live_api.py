#!/usr/bin/env python3
"""
End-to-end live API integration tests for the SkyFi MCP server.

Calls each safe read-only MCP tool against the real SkyFi and OpenStreetMap
APIs via the FastMCP in-process transport (equivalent to stdio).

Usage:
    SKYFI_API_KEY="sk-..." uv run python packages/core/tests/integration/test_live_api.py

Set VERBOSE=1 for full tracebacks on failures.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

# ---------------------------------------------------------------------------
# Path setup — mirror the entry-point shim so all imports resolve
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
for _p in [str(_PROJECT_ROOT), str(_PROJECT_ROOT / "packages" / "core")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    name: str
    group: str
    passed: bool = False
    skipped: bool = False
    error: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0


_results: list[TestResult] = []
_VERBOSE = bool(os.environ.get("VERBOSE"))


async def run_test(
    name: str,
    group: str,
    fn: Callable[[], Coroutine[Any, Any, dict[str, Any]]],
    *,
    validate: Callable[[dict[str, Any]], None] | None = None,
) -> TestResult:
    """Run a single test, record the result, and print a status line."""
    result = TestResult(name=name, group=group)
    start = time.monotonic()
    try:
        data = await fn()
        result.data = data if isinstance(data, dict) else {}
        if validate:
            validate(result.data)
        result.passed = True
        result.duration_ms = (time.monotonic() - start) * 1000
        print(f"  PASS  {name} ({result.duration_ms:.0f}ms)")
    except Exception as exc:
        result.duration_ms = (time.monotonic() - start) * 1000
        result.error = f"{type(exc).__name__}: {exc}"
        print(f"  FAIL  {name} ({result.duration_ms:.0f}ms)")
        print(f"        {result.error}")
        if _VERBOSE:
            traceback.print_exc()
    _results.append(result)
    return result


def skip_test(name: str, group: str, reason: str) -> None:
    """Record and print a skipped test."""
    _results.append(TestResult(name=name, group=group, skipped=True))
    print(f"  SKIP  {name} ({reason})")


def _assert(condition: Any, msg: str) -> None:
    """Raise AssertionError if condition is falsy."""
    if not condition:
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
# Main test sequence
# ---------------------------------------------------------------------------

async def main() -> int:
    api_key = os.environ.get("SKYFI_API_KEY")
    if not api_key:
        print("ERROR: SKYFI_API_KEY environment variable is not set.")
        print(
            "Usage: SKYFI_API_KEY='sk-...' uv run python "
            "packages/core/tests/integration/test_live_api.py"
        )
        return 1

    # Import the FastMCP server (triggers config loading)
    from fastmcp import Client

    from packages.server.local.server import mcp as server

    print()
    print("=" * 55)
    print("  SkyFi MCP  --  Live API Integration Tests")
    print("=" * 55)
    print()

    async with Client(server) as client:

        async def call(tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
            """Call an MCP tool and return the parsed JSON response."""
            raw = await client.call_tool(tool, args or {})
            # FastMCP Client returns list[Content] or CallToolResult
            content = raw if isinstance(raw, list) else getattr(raw, "content", raw)
            if content and hasattr(content[0], "text"):
                return json.loads(content[0].text)  # type: ignore[union-attr]
            return {}

        # Shared state for chaining dependent tests
        archive_id: str | None = None

        # ── Group 1: OSM tools (no API key needed) ─────────────
        print("--- OSM Tools (no API key needed) ---")

        r = await run_test(
            "geocode", "osm",
            lambda: call("geocode", {"query": "Eiffel Tower, Paris"}),
            validate=lambda d: _assert(d.get("results"), "expected non-empty results"),
        )
        if r.passed and r.data.get("results"):
            top = r.data["results"][0]
            print(f"        -> {top.get('display_name', '')[:60]}")

        await run_test(
            "reverse_geocode", "osm",
            lambda: call("reverse_geocode", {"lat": 48.8584, "lon": 2.2945}),
            validate=lambda d: _assert(d.get("address"), "expected address field"),
        )

        await run_test(
            "search_pois", "osm",
            lambda: call("search_pois", {
                "location": {"lat": 48.8584, "lon": 2.2945},
                "category": "commercial",
                "radius": 500,
            }),
            validate=lambda d: _assert("results" in d, "expected results key"),
        )

        await run_test(
            "get_area_boundary", "osm",
            lambda: call("get_area_boundary", {"name": "Paris", "admin_level": 8}),
            validate=lambda d: _assert(d.get("geometry"), "expected geometry"),
        )

        # ── Group 2: Search tools ──────────────────────────────
        print("\n--- Search Tools ---")

        eiffel_polygon: dict[str, Any] = {
            "type": "Polygon",
            "coordinates": [[
                [2.2935, 48.8574],
                [2.2955, 48.8574],
                [2.2955, 48.8594],
                [2.2935, 48.8594],
                [2.2935, 48.8574],
            ]],
        }

        r = await run_test(
            "search_archive", "search",
            lambda: call("search_archive", {
                "location": eiffel_polygon,
                "sensor_type": "optical",
            }),
            validate=lambda d: _assert("results" in d, "expected results key"),
        )
        if r.passed and r.data.get("results"):
            archive_id = r.data["results"][0]["archive_id"]
            n = len(r.data["results"])
            print(f"        -> {n} results, archive_id={archive_id[:30]}...")

        if archive_id:
            _aid = archive_id  # capture for lambda
            await run_test(
                "get_archive_details", "search",
                lambda: call("get_archive_details", {"archive_id": _aid}),
                validate=lambda d: _assert(d.get("archive_id"), "expected archive_id"),
            )
        else:
            skip_test("get_archive_details", "search", "no archive_id from search")

        await run_test(
            "explore_providers", "search",
            lambda: call("explore_providers", {}),
            validate=lambda d: _assert(d.get("providers"), "expected providers list"),
        )

        # ── Group 3: Pricing tools ─────────────────────────────
        print("\n--- Pricing Tools ---")

        if archive_id:
            _aid = archive_id
            await run_test(
                "estimate_archive_price", "pricing",
                lambda: call("estimate_archive_price", {"archive_id": _aid}),
                validate=lambda d: _assert(d.get("price"), "expected price"),
            )
        else:
            skip_test("estimate_archive_price", "pricing", "no archive_id")

        await run_test(
            "analyze_feasibility", "pricing",
            lambda: call("analyze_feasibility", {"location": eiffel_polygon}),
            validate=lambda d: _assert(
                "feasibility_score" in d, "expected feasibility_score"
            ),
        )

        await run_test(
            "compare_pricing", "pricing",
            lambda: call("compare_pricing", {
                "location": eiffel_polygon,
                "resolution_options": [0.5, 3.0],
            }),
            validate=lambda d: _assert("comparisons" in d, "expected comparisons"),
        )

        # ── Group 4: Order query tools ─────────────────────────
        print("\n--- Order Query Tools ---")

        await run_test(
            "list_orders", "orders",
            lambda: call("list_orders", {}),
            validate=lambda d: _assert("orders" in d, "expected orders key"),
        )

        await run_test(
            "check_notifications", "orders",
            lambda: call("check_notifications", {}),
            validate=lambda d: _assert(
                "notifications" in d, "expected notifications key"
            ),
        )

        # ── Group 5: Order preview (confirmed=false, no charge) ─
        print("\n--- Order Preview (confirmed=false, no charge) ---")

        if archive_id:
            _aid = archive_id
            r = await run_test(
                "place_archive_order_preview", "preview",
                lambda: call("place_archive_order", {
                    "archive_id": _aid,
                    "confirmed": False,
                }),
                validate=lambda d: _assert(
                    d.get("preview") is not None and d.get("confirmation") is None,
                    "expected preview (not confirmation)",
                ),
            )
            if r.passed:
                price = (r.data.get("preview") or {}).get("price", {})
                print(
                    f"        -> preview price: "
                    f"${price.get('total', '?')} {price.get('currency', 'USD')}"
                )
        else:
            skip_test(
                "place_archive_order_preview", "preview", "no archive_id"
            )

    # ── Summary ────────────────────────────────────────────────
    passed = sum(1 for r in _results if r.passed)
    failed = sum(1 for r in _results if not r.passed and not r.skipped)
    skipped = sum(1 for r in _results if r.skipped)
    total_ms = sum(r.duration_ms for r in _results)

    print()
    print("=" * 55)
    print(
        f"  {passed} passed, {failed} failed, {skipped} skipped"
        f"  ({total_ms / 1000:.1f}s)"
    )
    print("=" * 55)
    print()

    if failed:
        print("Failed tests:")
        for r in _results:
            if not r.passed and not r.skipped:
                print(f"  - {r.name}: {r.error}")
        print()

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
