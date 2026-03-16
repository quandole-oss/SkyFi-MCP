"""
Unit tests for thumbnail fetching utility.

Uses ``respx`` to mock HTTP requests.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from skyfi_mcp.thumbnails import FetchedThumbnail, encode_thumbnail_base64, fetch_thumbnails

# A minimal 1x1 JPEG for testing
TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.\' ',#\x1c\x1c(7),01444\x1f\'9=82<.342"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00T\xdb\x9e\xa7\x13\xff\xd9"
)


class TestFetchThumbnails:
    @respx.mock
    @pytest.mark.asyncio
    async def test_successful_fetch(self) -> None:
        """Successful fetch returns archive_id -> FetchedThumbnail mapping."""
        respx.get("https://cdn.example.com/thumb1.jpg").mock(
            return_value=httpx.Response(200, content=TINY_JPEG)
        )

        result = await fetch_thumbnails([("img-001", "https://cdn.example.com/thumb1.jpg")])

        assert "img-001" in result
        assert result["img-001"].data == TINY_JPEG
        assert result["img-001"].format == "jpeg"

    @respx.mock
    @pytest.mark.asyncio
    async def test_multiple_successful(self) -> None:
        """Multiple thumbnails fetched in parallel."""
        respx.get("https://cdn.example.com/a.jpg").mock(
            return_value=httpx.Response(200, content=b"img-a-bytes")
        )
        respx.get("https://cdn.example.com/b.jpg").mock(
            return_value=httpx.Response(200, content=b"img-b-bytes")
        )

        result = await fetch_thumbnails([
            ("img-a", "https://cdn.example.com/a.jpg"),
            ("img-b", "https://cdn.example.com/b.jpg"),
        ])

        assert len(result) == 2
        assert result["img-a"].data == b"img-a-bytes"
        assert result["img-b"].data == b"img-b-bytes"

    @respx.mock
    @pytest.mark.asyncio
    async def test_http_error_omitted(self) -> None:
        """404/500 responses are silently omitted."""
        respx.get("https://cdn.example.com/ok.jpg").mock(
            return_value=httpx.Response(200, content=b"ok-bytes")
        )
        respx.get("https://cdn.example.com/notfound.jpg").mock(
            return_value=httpx.Response(404)
        )

        result = await fetch_thumbnails([
            ("img-ok", "https://cdn.example.com/ok.jpg"),
            ("img-404", "https://cdn.example.com/notfound.jpg"),
        ])

        assert "img-ok" in result
        assert "img-404" not in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_timeout_omitted(self) -> None:
        """Timeout errors are silently omitted."""
        respx.get("https://cdn.example.com/ok.jpg").mock(
            return_value=httpx.Response(200, content=b"ok-bytes")
        )
        respx.get("https://cdn.example.com/slow.jpg").mock(
            side_effect=httpx.ReadTimeout("timed out")
        )

        result = await fetch_thumbnails([
            ("img-ok", "https://cdn.example.com/ok.jpg"),
            ("img-slow", "https://cdn.example.com/slow.jpg"),
        ])

        assert "img-ok" in result
        assert "img-slow" not in result

    @respx.mock
    @pytest.mark.asyncio
    async def test_connection_error_omitted(self) -> None:
        """Connection errors are silently omitted."""
        respx.get("https://cdn.example.com/fail.jpg").mock(
            side_effect=httpx.ConnectError("refused")
        )

        result = await fetch_thumbnails([
            ("img-fail", "https://cdn.example.com/fail.jpg"),
        ])

        assert len(result) == 0

    @respx.mock
    @pytest.mark.asyncio
    async def test_max_count_limits(self) -> None:
        """Only max_count thumbnails are fetched."""
        for i in range(5):
            respx.get(f"https://cdn.example.com/{i}.jpg").mock(
                return_value=httpx.Response(200, content=f"bytes-{i}".encode())
            )

        urls = [(f"img-{i}", f"https://cdn.example.com/{i}.jpg") for i in range(5)]
        result = await fetch_thumbnails(urls, max_count=2)

        assert len(result) == 2
        assert "img-0" in result
        assert "img-1" in result
        assert "img-2" not in result

    @pytest.mark.asyncio
    async def test_empty_url_list(self) -> None:
        """Empty URL list returns empty dict."""
        result = await fetch_thumbnails([])
        assert result == {}

    @respx.mock
    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(self) -> None:
        """Mix of success, 500 error, and timeout."""
        respx.get("https://cdn.example.com/a.jpg").mock(
            return_value=httpx.Response(200, content=b"a-bytes")
        )
        respx.get("https://cdn.example.com/b.jpg").mock(
            return_value=httpx.Response(500)
        )
        respx.get("https://cdn.example.com/c.jpg").mock(
            side_effect=httpx.ReadTimeout("slow")
        )

        result = await fetch_thumbnails([
            ("a", "https://cdn.example.com/a.jpg"),
            ("b", "https://cdn.example.com/b.jpg"),
            ("c", "https://cdn.example.com/c.jpg"),
        ])

        assert len(result) == 1
        assert result["a"].data == b"a-bytes"


class TestEncodeThumbnailBase64:
    def test_encode(self) -> None:
        result = encode_thumbnail_base64(b"hello")
        assert result == "aGVsbG8="

    def test_encode_empty(self) -> None:
        result = encode_thumbnail_base64(b"")
        assert result == ""
