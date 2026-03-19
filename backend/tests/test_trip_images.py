"""Tests for backend.trip_images."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestTripImagePath:
    def test_path_format(self, test_db):
        from backend.trip_images import trip_image_path

        p = trip_image_path("my-trip-123")
        assert p.name == "my-trip-123.jpg"
        assert "trips" in str(p)

    def test_images_dir_created(self, test_db):
        from backend.trip_images import trip_image_path

        p = trip_image_path("abc")
        assert p.parent.exists()


class TestParseJsonSafe:
    def test_returns_dict_for_200(self):
        from backend.trip_images import _parse_json_safe

        mock_r = MagicMock()
        mock_r.status_code = 200
        mock_r.json.return_value = {"query": {"pages": []}}
        result = _parse_json_safe(mock_r)
        assert result == {"query": {"pages": []}}

    def test_returns_empty_for_non_200(self):
        from backend.trip_images import _parse_json_safe

        mock_r = MagicMock()
        mock_r.status_code = 404
        mock_r.text = "not found"
        result = _parse_json_safe(mock_r)
        assert result == {}

    def test_returns_empty_on_json_error(self):
        from backend.trip_images import _parse_json_safe

        mock_r = MagicMock()
        mock_r.status_code = 200
        mock_r.json.side_effect = ValueError("bad json")
        result = _parse_json_safe(mock_r)
        assert result == {}


class TestGetPhotoUrls:
    def test_returns_urls_from_generator(self):
        from backend.trip_images import _get_photo_urls

        fake_response = {
            "query": {
                "pages": [
                    {
                        "title": "File:London_skyline.jpg",
                        "imageinfo": [
                            {
                                "mime": "image/jpeg",
                                "thumburl": "https://example.com/thumb.jpg",
                                "thumbwidth": 1000,
                                "thumbheight": 600,
                                "url": "https://example.com/full.jpg",
                                "width": 1000,
                                "height": 600,
                            }
                        ],
                    }
                ]
            }
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_response

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            urls = asyncio.run(_get_photo_urls("London"))

        assert "https://example.com/thumb.jpg" in urls

    def test_skips_flag_images(self):
        from backend.trip_images import _get_photo_urls

        fake_response = {
            "query": {
                "pages": [
                    {
                        "title": "File:Flag_of_London.jpg",
                        "imageinfo": [
                            {
                                "mime": "image/jpeg",
                                "url": "https://example.com/flag.jpg",
                                "width": 1000,
                                "height": 600,
                            }
                        ],
                    }
                ]
            }
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_response

        fallback_resp = MagicMock()
        fallback_resp.status_code = 200
        fallback_resp.json.return_value = {"query": {"pages": []}}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[mock_resp, fallback_resp])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            urls = asyncio.run(_get_photo_urls("London"))

        assert "https://example.com/flag.jpg" not in urls

    def test_falls_back_to_thumbnail(self):
        from backend.trip_images import _get_photo_urls

        empty_resp = MagicMock()
        empty_resp.status_code = 200
        empty_resp.json.return_value = {"query": {"pages": []}}

        thumb_resp = MagicMock()
        thumb_resp.status_code = 200
        thumb_resp.json.return_value = {
            "query": {"pages": [{"thumbnail": {"source": "https://example.com/main_thumb.jpg"}}]}
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[empty_resp, thumb_resp])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            urls = asyncio.run(_get_photo_urls("London"))

        assert urls == ["https://example.com/main_thumb.jpg"]

    def test_returns_empty_when_no_images(self):
        from backend.trip_images import _get_photo_urls

        empty = MagicMock()
        empty.status_code = 200
        empty.json.return_value = {"query": {"pages": []}}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=empty)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            urls = asyncio.run(_get_photo_urls("NoCity"))

        assert urls == []

    def test_skips_non_jpeg(self):
        from backend.trip_images import _get_photo_urls

        fake_response = {
            "query": {
                "pages": [
                    {
                        "title": "File:London.png",
                        "imageinfo": [
                            {
                                "mime": "image/png",
                                "url": "https://example.com/image.png",
                                "width": 1000,
                                "height": 600,
                            }
                        ],
                    }
                ]
            }
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_response

        fallback = MagicMock()
        fallback.status_code = 200
        fallback.json.return_value = {"query": {"pages": []}}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[mock_resp, fallback])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            urls = asyncio.run(_get_photo_urls("London"))

        assert "https://example.com/image.png" not in urls


class TestFetchTripImage:
    def test_returns_true_when_file_exists(self, test_db):
        from backend.trip_images import fetch_trip_image, trip_image_path

        p = trip_image_path("existing-trip")
        p.write_bytes(b"fake image data")
        result = asyncio.run(fetch_trip_image("existing-trip", "London"))
        assert result is True

    def test_force_refresh_deletes_existing(self, test_db):
        from backend.trip_images import fetch_trip_image, trip_image_path

        p = trip_image_path("trip-refresh")
        p.write_bytes(b"old image")

        with patch("backend.trip_images._get_photo_urls", AsyncMock(return_value=[])):
            result = asyncio.run(fetch_trip_image("trip-refresh", "London", force_refresh=True))

        assert not p.exists()
        assert result is False

    def test_returns_false_when_no_urls(self, test_db):
        from backend.trip_images import fetch_trip_image

        with patch("backend.trip_images._get_photo_urls", AsyncMock(return_value=[])):
            result = asyncio.run(fetch_trip_image("no-image-trip", "NoCity"))

        assert result is False

    def test_downloads_and_saves_image(self, test_db):
        from backend.trip_images import fetch_trip_image, trip_image_path

        fake_content = b"\xff\xd8\xff fake jpeg"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = fake_content

        mock_dl_client = AsyncMock()
        mock_dl_client.get = AsyncMock(return_value=mock_resp)
        mock_dl_client.__aenter__ = AsyncMock(return_value=mock_dl_client)
        mock_dl_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "backend.trip_images._get_photo_urls",
            AsyncMock(return_value=["https://example.com/img.jpg"]),
        ):
            with patch("httpx.AsyncClient", return_value=mock_dl_client):
                result = asyncio.run(fetch_trip_image("download-trip", "London"))

        assert result is True
        p = trip_image_path("download-trip")
        assert p.exists()
        assert p.read_bytes() == fake_content

    def test_download_exception_tries_next_url(self, test_db):
        from backend.trip_images import fetch_trip_image

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.content = b"image data"

        async def _side_effect(url, **kw):
            if "bad" in url:
                raise OSError("connection refused")
            return ok_resp

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=_side_effect)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "backend.trip_images._get_photo_urls",
            AsyncMock(return_value=["https://bad.com/img.jpg", "https://good.com/img.jpg"]),
        ):
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = asyncio.run(fetch_trip_image("multi-url-trip", "London"))

        assert result is True
