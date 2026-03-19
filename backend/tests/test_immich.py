"""Tests for backend.immich and the immich-album route endpoints."""

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
        from backend.immich import test_connection

        ping = self._make_response(200)
        about = self._make_response(200, {"version": "v1.100.0"})
        search = self._make_response(200)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[ping, about])
        mock_client.post = AsyncMock(return_value=search)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.immich.httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(test_connection("https://immich.example.com", "key123"))

        assert result == {"ok": True, "version": "v1.100.0"}

    def test_unknown_version_when_about_fails(self):
        from backend.immich import test_connection

        ping = self._make_response(200)
        about = self._make_response(403)
        search = self._make_response(200)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[ping, about])
        mock_client.post = AsyncMock(return_value=search)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.immich.httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(test_connection("https://immich.example.com", "key123"))

        assert result["version"] == "unknown"

    def test_unreachable_server_raises_value_error(self):
        from backend.immich import test_connection

        ping = self._make_response(503)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=ping)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.immich.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ValueError, match="Server not reachable"):
                asyncio.run(test_connection("https://immich.example.com", "key123"))

    def test_invalid_api_key_raises_value_error(self):
        from backend.immich import test_connection

        ping = self._make_response(200)
        about = self._make_response(200, {"version": "v1.0.0"})
        search = self._make_response(401)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[ping, about])
        mock_client.post = AsyncMock(return_value=search)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.immich.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ValueError, match="Invalid API key"):
                asyncio.run(test_connection("https://immich.example.com", "badkey"))

    def test_missing_permissions_raises_value_error(self):
        from backend.immich import test_connection

        ping = self._make_response(200)
        about = self._make_response(200, {"version": "v1.0.0"})
        search = self._make_response(403)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[ping, about])
        mock_client.post = AsyncMock(return_value=search)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.immich.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ValueError, match="lacks required permissions"):
                asyncio.run(test_connection("https://immich.example.com", "key123"))

    def test_timeout_raises_value_error(self):
        import httpx

        from backend.immich import test_connection

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.immich.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ValueError, match="timed out"):
                asyncio.run(test_connection("https://immich.example.com", "key123"))


class TestAlbumExists:
    def _make_response(self, status_code):
        resp = MagicMock()
        resp.status_code = status_code
        return resp

    def test_returns_true_when_200(self):
        from backend.immich import album_exists

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=self._make_response(200))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.immich.httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(album_exists("https://immich.example.com", "key", "album-id"))

        assert result is True

    def test_returns_false_when_404(self):
        from backend.immich import album_exists

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=self._make_response(404))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.immich.httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(album_exists("https://immich.example.com", "key", "album-id"))

        assert result is False

    def test_returns_true_on_403_not_treated_as_deleted(self):
        from backend.immich import album_exists

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=self._make_response(403))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.immich.httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(album_exists("https://immich.example.com", "key", "album-id"))

        assert result is True

    def test_returns_true_on_network_error(self):
        from backend.immich import album_exists

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("network error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.immich.httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(album_exists("https://immich.example.com", "key", "album-id"))

        assert result is True


class TestCreateTripAlbum:
    def test_creates_album_and_returns_info(self):
        from backend.immich import create_trip_album

        with patch(
            "backend.immich._get_asset_ids_in_range", new=AsyncMock(return_value=["a1", "a2"])
        ):
            album_resp = MagicMock()
            album_resp.status_code = 201
            album_resp.json.return_value = {"id": "new-album-id"}

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=album_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)

            with patch("backend.immich.httpx.AsyncClient", return_value=mock_client):
                result = asyncio.run(
                    create_trip_album(
                        "https://immich.example.com", "key", "My Trip", "2024-01-01", "2024-01-10"
                    )
                )

        assert result["album_id"] == "new-album-id"
        assert "albums/new-album-id" in result["album_url"]
        assert result["asset_count"] == 2

    def test_raises_on_api_error(self):
        from backend.immich import create_trip_album

        with patch("backend.immich._get_asset_ids_in_range", new=AsyncMock(return_value=[])):
            err_resp = MagicMock()
            err_resp.status_code = 500
            err_resp.text = "Internal Server Error"

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=err_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)

            with patch("backend.immich.httpx.AsyncClient", return_value=mock_client):
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


# ---------------------------------------------------------------------------
# Route integration tests
# ---------------------------------------------------------------------------


def _setup_user_with_immich(client, immich_url="https://immich.example.com", api_key="testkey"):
    """Create admin user, log in, configure Immich settings."""
    client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
    from backend.database import db_write

    with db_write() as conn:
        conn.execute(
            "UPDATE users SET immich_url = ?, immich_api_key = ? WHERE username = 'admin'",
            (immich_url, api_key),
        )


def _create_trip(client, name="Paris Trip", start="2024-06-01", end="2024-06-10"):
    """Create a trip via the API and return the trip dict."""
    resp = client.post("/api/trips", json={"name": name, "start_date": start, "end_date": end})
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


class TestCreateImmichAlbumRoute:
    def test_creates_album_successfully(self, client, test_db):
        _setup_user_with_immich(client)
        trip = _create_trip(client)

        with (
            patch("backend.immich.album_exists", new=AsyncMock(return_value=False)),
            patch(
                "backend.immich.create_trip_album",
                new=AsyncMock(
                    return_value={
                        "album_id": "abc-123",
                        "album_url": "https://immich.example.com/albums/abc-123",
                        "asset_count": 5,
                    }
                ),
            ),
        ):
            resp = client.post(f"/api/trips/{trip['id']}/immich-album")

        assert resp.status_code == 200
        data = resp.json()
        assert data["album_id"] == "abc-123"
        assert data["asset_count"] == 5
        assert data["already_exists"] is False

    def test_returns_existing_album_if_still_exists(self, client, test_db):
        _setup_user_with_immich(client)
        trip = _create_trip(client)

        # Store an album_id in the DB
        from backend.database import db_write

        with db_write() as conn:
            conn.execute(
                "UPDATE trips SET immich_album_id = ? WHERE id = ?",
                ("existing-album-id", trip["id"]),
            )

        with patch("backend.immich.album_exists", new=AsyncMock(return_value=True)):
            resp = client.post(f"/api/trips/{trip['id']}/immich-album")

        assert resp.status_code == 200
        data = resp.json()
        assert data["album_id"] == "existing-album-id"
        assert data["already_exists"] is True

    def test_recreates_album_if_deleted_in_immich(self, client, test_db):
        _setup_user_with_immich(client)
        trip = _create_trip(client)

        from backend.database import db_write

        with db_write() as conn:
            conn.execute(
                "UPDATE trips SET immich_album_id = ? WHERE id = ?",
                ("deleted-album-id", trip["id"]),
            )

        with (
            patch("backend.immich.album_exists", new=AsyncMock(return_value=False)),
            patch(
                "backend.immich.create_trip_album",
                new=AsyncMock(
                    return_value={
                        "album_id": "new-album-id",
                        "album_url": "https://immich.example.com/albums/new-album-id",
                        "asset_count": 3,
                    }
                ),
            ),
        ):
            resp = client.post(f"/api/trips/{trip['id']}/immich-album")

        assert resp.status_code == 200
        data = resp.json()
        assert data["album_id"] == "new-album-id"
        assert data["already_exists"] is False

    def test_returns_404_for_unknown_trip(self, client, test_db):
        _setup_user_with_immich(client)
        resp = client.post("/api/trips/nonexistent-id/immich-album")
        assert resp.status_code == 404

    def test_returns_400_when_immich_not_configured(self, client, test_db):
        # Log in without setting up Immich
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        trip = _create_trip(client)
        resp = client.post(f"/api/trips/{trip['id']}/immich-album")
        assert resp.status_code == 400
        assert "not configured" in resp.json()["detail"].lower()

    def test_returns_400_when_trip_has_no_dates(self, client, test_db):
        _setup_user_with_immich(client)
        resp = client.post("/api/trips", json={"name": "No Dates"})
        assert resp.status_code in (200, 201)
        trip = resp.json()
        resp = client.post(f"/api/trips/{trip['id']}/immich-album")
        assert resp.status_code == 400
        assert "dates" in resp.json()["detail"].lower()


class TestCheckImmichAlbumRoute:
    def test_returns_exists_true_when_album_found(self, client, test_db):
        _setup_user_with_immich(client)
        trip = _create_trip(client)

        from backend.database import db_write

        with db_write() as conn:
            conn.execute(
                "UPDATE trips SET immich_album_id = ? WHERE id = ?",
                ("album-123", trip["id"]),
            )

        with patch("backend.immich.album_exists", new=AsyncMock(return_value=True)):
            resp = client.get(f"/api/trips/{trip['id']}/immich-album/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["exists"] is True
        assert data["album_id"] == "album-123"

    def test_returns_exists_false_when_album_deleted(self, client, test_db):
        _setup_user_with_immich(client)
        trip = _create_trip(client)

        from backend.database import db_write

        with db_write() as conn:
            conn.execute(
                "UPDATE trips SET immich_album_id = ? WHERE id = ?",
                ("deleted-album", trip["id"]),
            )

        with patch("backend.immich.album_exists", new=AsyncMock(return_value=False)):
            resp = client.get(f"/api/trips/{trip['id']}/immich-album/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["exists"] is False
        assert data["album_id"] is None

    def test_returns_exists_false_when_no_album_stored(self, client, test_db):
        _setup_user_with_immich(client)
        trip = _create_trip(client)
        resp = client.get(f"/api/trips/{trip['id']}/immich-album/status")
        assert resp.status_code == 200
        assert resp.json() == {"album_id": None, "exists": False}

    def test_assumes_exists_when_immich_not_configured(self, client, test_db):
        client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        trip = _create_trip(client)

        from backend.database import db_write

        with db_write() as conn:
            conn.execute(
                "UPDATE trips SET immich_album_id = ? WHERE id = ?",
                ("some-album", trip["id"]),
            )

        resp = client.get(f"/api/trips/{trip['id']}/immich-album/status")
        assert resp.status_code == 200
        assert resp.json()["exists"] is True
