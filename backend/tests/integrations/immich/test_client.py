"""Tests for backend.integrations.immich.client (the Immich HTTP client module).

The /api/trips/{id}/immich-album* route tests live in
backend/tests/trips/test_api_trips_immich.py instead — they exercise the trips
feature's routes, not this module directly."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# immich.py unit tests
# ---------------------------------------------------------------------------


class TestTestConnection:
    def _make_response(self, status_code, json_data=None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data or {}
        return resp

    def test_successful_connection_returns_version(self):
        from backend.integrations.immich.client import test_connection

        ping = self._make_response(200)
        about = self._make_response(200, {"version": "v1.100.0"})
        search = self._make_response(200)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[ping, about])
        mock_client.post = AsyncMock(return_value=search)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "backend.integrations.immich.client.httpx.AsyncClient", return_value=mock_client
        ):
            result = asyncio.run(test_connection("https://immich.example.com", "key123"))

        assert result == {"ok": True, "version": "v1.100.0"}

    def test_unknown_version_when_about_fails(self):
        from backend.integrations.immich.client import test_connection

        ping = self._make_response(200)
        about = self._make_response(403)
        search = self._make_response(200)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[ping, about])
        mock_client.post = AsyncMock(return_value=search)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "backend.integrations.immich.client.httpx.AsyncClient", return_value=mock_client
        ):
            result = asyncio.run(test_connection("https://immich.example.com", "key123"))

        assert result["version"] == "unknown"

    def test_unreachable_server_raises_value_error(self):
        from backend.integrations.immich.client import test_connection

        ping = self._make_response(503)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=ping)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "backend.integrations.immich.client.httpx.AsyncClient", return_value=mock_client
        ):
            with pytest.raises(ValueError, match="Server not reachable"):
                asyncio.run(test_connection("https://immich.example.com", "key123"))

    def test_invalid_api_key_raises_value_error(self):
        from backend.integrations.immich.client import test_connection

        ping = self._make_response(200)
        about = self._make_response(200, {"version": "v1.0.0"})
        search = self._make_response(401)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[ping, about])
        mock_client.post = AsyncMock(return_value=search)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "backend.integrations.immich.client.httpx.AsyncClient", return_value=mock_client
        ):
            with pytest.raises(ValueError, match="Invalid API key"):
                asyncio.run(test_connection("https://immich.example.com", "badkey"))

    def test_missing_permissions_raises_value_error(self):
        from backend.integrations.immich.client import test_connection

        ping = self._make_response(200)
        about = self._make_response(200, {"version": "v1.0.0"})
        search = self._make_response(403)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[ping, about])
        mock_client.post = AsyncMock(return_value=search)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "backend.integrations.immich.client.httpx.AsyncClient", return_value=mock_client
        ):
            with pytest.raises(ValueError, match="lacks required permissions"):
                asyncio.run(test_connection("https://immich.example.com", "key123"))

    def test_timeout_raises_value_error(self):
        import httpx

        from backend.integrations.immich.client import test_connection

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "backend.integrations.immich.client.httpx.AsyncClient", return_value=mock_client
        ):
            with pytest.raises(ValueError, match="timed out"):
                asyncio.run(test_connection("https://immich.example.com", "key123"))


class TestAlbumExists:
    def _make_response(self, status_code):
        resp = MagicMock()
        resp.status_code = status_code
        return resp

    def test_returns_true_when_200(self):
        from backend.integrations.immich.client import album_exists

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=self._make_response(200))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "backend.integrations.immich.client.httpx.AsyncClient", return_value=mock_client
        ):
            result = asyncio.run(album_exists("https://immich.example.com", "key", "album-id"))

        assert result is True

    def test_returns_false_when_404(self):
        from backend.integrations.immich.client import album_exists

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=self._make_response(404))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "backend.integrations.immich.client.httpx.AsyncClient", return_value=mock_client
        ):
            result = asyncio.run(album_exists("https://immich.example.com", "key", "album-id"))

        assert result is False

    def test_returns_true_on_403_not_treated_as_deleted(self):
        from backend.integrations.immich.client import album_exists

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=self._make_response(403))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "backend.integrations.immich.client.httpx.AsyncClient", return_value=mock_client
        ):
            result = asyncio.run(album_exists("https://immich.example.com", "key", "album-id"))

        assert result is True

    def test_returns_true_on_network_error(self):
        from backend.integrations.immich.client import album_exists

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("network error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "backend.integrations.immich.client.httpx.AsyncClient", return_value=mock_client
        ):
            result = asyncio.run(album_exists("https://immich.example.com", "key", "album-id"))

        assert result is True


class TestCreateTripAlbum:
    def test_creates_album_and_returns_info(self):
        from backend.integrations.immich.client import create_trip_album

        with patch(
            "backend.integrations.immich.client._get_asset_ids_in_range",
            new=AsyncMock(return_value=["a1", "a2"]),
        ):
            album_resp = MagicMock()
            album_resp.status_code = 201
            album_resp.json.return_value = {"id": "new-album-id"}

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=album_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)

            with patch(
                "backend.integrations.immich.client.httpx.AsyncClient", return_value=mock_client
            ):
                result = asyncio.run(
                    create_trip_album(
                        "https://immich.example.com", "key", "My Trip", "2024-01-01", "2024-01-10"
                    )
                )

        assert result["album_id"] == "new-album-id"
        assert "albums/new-album-id" in result["album_url"]
        assert result["asset_count"] == 2

    def test_raises_on_api_error(self):
        from backend.integrations.immich.client import create_trip_album

        with patch(
            "backend.integrations.immich.client._get_asset_ids_in_range",
            new=AsyncMock(return_value=[]),
        ):
            err_resp = MagicMock()
            err_resp.status_code = 500
            err_resp.text = "Internal Server Error"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=err_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)

            with patch(
                "backend.integrations.immich.client.httpx.AsyncClient", return_value=mock_client
            ):
                with pytest.raises(ValueError, match="Failed to create album"):
                    asyncio.run(
                        create_trip_album(
                            "https://immich.example.com",
                            "key",
                            "My Trip",
                            "2024-01-01",
                            "2024-01-10",
                        )
                    )
