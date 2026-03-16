"""
Thumbnail fetching utility.

Fetches satellite image thumbnails in parallel for embedding in MCP responses.
Uses httpx.AsyncClient (already a project dependency) with per-image timeouts.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class FetchedThumbnail:
    """A fetched thumbnail with its detected format."""

    data: bytes
    format: str  # "png", "jpeg", "webp", "gif"


def detect_image_format(data: bytes) -> str:
    """Detect image format from magic bytes. Defaults to 'png'."""
    if data[:2] == b"\xff\xd8":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return "png"


async def fetch_thumbnails(
    urls: list[tuple[str, str]],
    max_count: int = 5,
    timeout_seconds: float = 5.0,
    max_bytes: int = 200_000,
) -> dict[str, FetchedThumbnail]:
    """Fetch thumbnail images in parallel and return bytes with format.

    Args:
        urls: List of (archive_id, url) pairs to fetch.
        max_count: Maximum number of thumbnails to fetch.
        timeout_seconds: Per-image timeout in seconds.
        max_bytes: Maximum size in bytes per thumbnail; larger images are skipped.

    Returns:
        Dict mapping archive_id to FetchedThumbnail.
        Failed fetches are silently omitted.
    """
    if not urls:
        return {}

    # Limit to max_count
    to_fetch = urls[:max_count]

    async def _fetch_one(
        client: httpx.AsyncClient, archive_id: str, url: str
    ) -> tuple[str, FetchedThumbnail] | None:
        try:
            resp = await client.get(url, timeout=timeout_seconds)
            resp.raise_for_status()
            if len(resp.content) > max_bytes:
                logger.debug(
                    "Thumbnail for %s too large (%d bytes), skipping",
                    archive_id,
                    len(resp.content),
                )
                return None
            fmt = detect_image_format(resp.content)
            return (archive_id, FetchedThumbnail(data=resp.content, format=fmt))
        except (httpx.HTTPError, httpx.TimeoutException):
            logger.debug("Failed to fetch thumbnail for %s: %s", archive_id, url)
            return None

    async with httpx.AsyncClient() as client:
        tasks = [_fetch_one(client, aid, url) for aid, url in to_fetch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    thumbnails: dict[str, FetchedThumbnail] = {}
    for result in results:
        if isinstance(result, tuple):
            thumbnails[result[0]] = result[1]
    return thumbnails


def encode_thumbnail_base64(data: bytes) -> str:
    """Encode raw image bytes as base64 string."""
    return base64.b64encode(data).decode("ascii")
