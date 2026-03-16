"""
Unit tests for _inject_thumbnail_data_uris in the local MCP server.

Tests the helper directly (no HTTP mocking needed) to verify:
- data URIs are embedded for successful thumbnails
- thumbnail_url is always stripped (even on failure / when thumbnails disabled)
- single-result (get_archive_details) and list-of-results (search_archive) shapes
"""

from __future__ import annotations

import base64
import os

import pytest
from skyfi_mcp.thumbnails import FetchedThumbnail

# The server module loads config at import time — set a dummy API key
os.environ.setdefault("SKYFI_API_KEY", "sk-test-dummy")

from packages.server.local.server import _inject_thumbnail_data_uris


# A tiny JPEG for realistic testing
TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
)

# A PNG header
TINY_PNG = b"\x89PNG\r\n\x1a\nfakedata"


class TestInjectSearchResults:
    """Tests for search_archive shape (list of results)."""

    def test_injects_data_uri_and_strips_url(self) -> None:
        """Successful thumbnail gets data URI; thumbnail_url removed."""
        result_dict = {
            "results": [
                {"archive_id": "img-001", "thumbnail_url": "https://cdn.example.com/1.jpg"},
                {"archive_id": "img-002", "thumbnail_url": "https://cdn.example.com/2.jpg"},
            ],
            "total": 2,
        }
        thumbs = {
            "img-001": FetchedThumbnail(data=TINY_JPEG, format="jpeg"),
            "img-002": FetchedThumbnail(data=TINY_PNG, format="png"),
        }

        _inject_thumbnail_data_uris(result_dict, thumbs)

        # Both should have data URIs
        b64_1 = base64.b64encode(TINY_JPEG).decode("ascii")
        assert result_dict["results"][0]["thumbnail_data_uri"] == f"data:image/jpeg;base64,{b64_1}"

        b64_2 = base64.b64encode(TINY_PNG).decode("ascii")
        assert result_dict["results"][1]["thumbnail_data_uri"] == f"data:image/png;base64,{b64_2}"

        # thumbnail_url should be gone
        assert "thumbnail_url" not in result_dict["results"][0]
        assert "thumbnail_url" not in result_dict["results"][1]

    def test_partial_fetch_failure(self) -> None:
        """Only successful fetches get data URIs; all thumbnail_urls stripped."""
        result_dict = {
            "results": [
                {"archive_id": "img-ok", "thumbnail_url": "https://cdn.example.com/ok.jpg"},
                {"archive_id": "img-fail", "thumbnail_url": "https://cdn.example.com/fail.jpg"},
            ],
        }
        thumbs = {
            "img-ok": FetchedThumbnail(data=TINY_JPEG, format="jpeg"),
            # img-fail is missing — fetch failed
        }

        _inject_thumbnail_data_uris(result_dict, thumbs)

        assert "thumbnail_data_uri" in result_dict["results"][0]
        assert "thumbnail_data_uri" not in result_dict["results"][1]
        assert "thumbnail_url" not in result_dict["results"][0]
        assert "thumbnail_url" not in result_dict["results"][1]

    def test_no_thumbnails_fetched(self) -> None:
        """When all fetches fail, no data URIs added, but thumbnail_urls still stripped."""
        result_dict = {
            "results": [
                {"archive_id": "img-001", "thumbnail_url": "https://cdn.example.com/1.jpg"},
            ],
        }

        _inject_thumbnail_data_uris(result_dict, {})

        assert "thumbnail_data_uri" not in result_dict["results"][0]
        assert "thumbnail_url" not in result_dict["results"][0]

    def test_no_thumbnail_url_field(self) -> None:
        """Results without thumbnail_url are handled gracefully."""
        result_dict = {
            "results": [
                {"archive_id": "img-001"},
            ],
        }

        _inject_thumbnail_data_uris(result_dict, {})

        assert "thumbnail_data_uri" not in result_dict["results"][0]
        assert "thumbnail_url" not in result_dict["results"][0]

    def test_empty_results_list(self) -> None:
        """Empty results list is handled without error."""
        result_dict: dict = {"results": [], "total": 0}

        _inject_thumbnail_data_uris(result_dict, {})

        assert result_dict["results"] == []

    def test_max_count_leaves_extras_without_data_uri(self) -> None:
        """Results beyond max_count get thumbnail_url stripped but no data URI."""
        result_dict = {
            "results": [
                {"archive_id": f"img-{i}", "thumbnail_url": f"https://cdn.example.com/{i}.jpg"}
                for i in range(10)
            ],
        }
        # Only first 5 had thumbnails fetched
        thumbs = {
            f"img-{i}": FetchedThumbnail(data=TINY_JPEG, format="jpeg")
            for i in range(5)
        }

        _inject_thumbnail_data_uris(result_dict, thumbs)

        for i in range(5):
            assert "thumbnail_data_uri" in result_dict["results"][i]
        for i in range(5, 10):
            assert "thumbnail_data_uri" not in result_dict["results"][i]
        # All should have thumbnail_url stripped
        for i in range(10):
            assert "thumbnail_url" not in result_dict["results"][i]


class TestInjectDetailResult:
    """Tests for get_archive_details shape (single result at top level)."""

    def test_injects_data_uri_and_strips_url(self) -> None:
        result_dict = {
            "archive_id": "img-001",
            "thumbnail_url": "https://cdn.example.com/1.jpg",
            "provider": "PLANET",
        }
        thumbs = {
            "img-001": FetchedThumbnail(data=TINY_PNG, format="png"),
        }

        _inject_thumbnail_data_uris(result_dict, thumbs)

        b64 = base64.b64encode(TINY_PNG).decode("ascii")
        assert result_dict["thumbnail_data_uri"] == f"data:image/png;base64,{b64}"
        assert "thumbnail_url" not in result_dict

    def test_no_thumbnail_fetched(self) -> None:
        """Failed fetch: no data URI, but thumbnail_url still stripped."""
        result_dict = {
            "archive_id": "img-001",
            "thumbnail_url": "https://cdn.example.com/1.jpg",
        }

        _inject_thumbnail_data_uris(result_dict, {})

        assert "thumbnail_data_uri" not in result_dict
        assert "thumbnail_url" not in result_dict

    def test_no_thumbnail_url_originally(self) -> None:
        """Result with no thumbnail_url — nothing to strip or inject."""
        result_dict = {
            "archive_id": "img-001",
            "provider": "PLANET",
        }

        _inject_thumbnail_data_uris(result_dict, {})

        assert "thumbnail_data_uri" not in result_dict
        assert "thumbnail_url" not in result_dict
