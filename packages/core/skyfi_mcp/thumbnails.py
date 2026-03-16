"""
Thumbnail fetching utility.

Fetches satellite image thumbnails in parallel for embedding in MCP responses.
Uses httpx.AsyncClient (already a project dependency) with per-image timeouts.
"""

from __future__ import annotations

import asyncio
import base64
import logging

import httpx

logger = logging.getLogger(__name__)


async def fetch_thumbnails(
    urls: list[tuple[str, str]],
    max_count: int = 5,
    timeout_seconds: float = 5.0,
) -> dict[str, bytes]:
    """Fetch thumbnail images in parallel and return raw bytes.

    Args:
        urls: List of (archive_id, url) pairs to fetch.
        max_count: Maximum number of thumbnails to fetch.
        timeout_seconds: Per-image timeout in seconds.

    Returns:
        Dict mapping archive_id to raw image bytes.
        Failed fetches are silently omitted.
    """
    if not urls:
        return {}

    # Limit to max_count
    to_fetch = urls[:max_count]

    async def _fetch_one(
        client: httpx.AsyncClient, archive_id: str, url: str
    ) -> tuple[str, bytes] | None:
        try:
            resp = await client.get(url, timeout=timeout_seconds)
            resp.raise_for_status()
            return (archive_id, resp.content)
        except (httpx.HTTPError, httpx.TimeoutException):
            logger.debug("Failed to fetch thumbnail for %s: %s", archive_id, url)
            return None

    async with httpx.AsyncClient() as client:
        tasks = [_fetch_one(client, aid, url) for aid, url in to_fetch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    thumbnails: dict[str, bytes] = {}
    for result in results:
        if isinstance(result, tuple):
            thumbnails[result[0]] = result[1]
    return thumbnails


def encode_thumbnail_base64(data: bytes) -> str:
    """Encode raw image bytes as base64 string."""
    return base64.b64encode(data).decode("ascii")
