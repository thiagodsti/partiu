"""Tests for the /api/trips/{id}/immich-album* route endpoints."""

from unittest.mock import AsyncMock, patch


def _setup_user_with_immich(client, immich_url="https://immich.example.com", api_key="testkey"):
    """Create admin user, log in, configure Immich settings."""
    client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
    from backend.database import db_write

    with db_write() as conn:
        conn.execute(
            "UPDATE users SET immich_url = ?, immich_api_key = ? WHERE username = 'admin'",
            (immich_url, api_key),
        )


def _store_album_id(trip_id: str, album_id: str) -> None:
    """Seed trip_immich_albums for the admin user (id=1)."""
    from backend.database import db_write

    with db_write() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO trip_immich_albums (trip_id, user_id, album_id) VALUES (?, 1, ?)",
            (trip_id, album_id),
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
            patch(
                "backend.integrations.immich.client.album_exists", new=AsyncMock(return_value=False)
            ),
            patch(
                "backend.integrations.immich.client.create_trip_album",
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
        _store_album_id(trip["id"], "existing-album-id")

        with patch(
            "backend.integrations.immich.client.album_exists", new=AsyncMock(return_value=True)
        ):
            resp = client.post(f"/api/trips/{trip['id']}/immich-album")

        assert resp.status_code == 200
        data = resp.json()
        assert data["album_id"] == "existing-album-id"
        assert data["already_exists"] is True

    def test_recreates_album_if_deleted_in_immich(self, client, test_db):
        _setup_user_with_immich(client)
        trip = _create_trip(client)
        _store_album_id(trip["id"], "deleted-album-id")

        with (
            patch(
                "backend.integrations.immich.client.album_exists", new=AsyncMock(return_value=False)
            ),
            patch(
                "backend.integrations.immich.client.create_trip_album",
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
        _store_album_id(trip["id"], "album-123")

        with patch(
            "backend.integrations.immich.client.album_exists", new=AsyncMock(return_value=True)
        ):
            resp = client.get(f"/api/trips/{trip['id']}/immich-album/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["exists"] is True
        assert data["album_id"] == "album-123"

    def test_returns_exists_false_when_album_deleted(self, client, test_db):
        _setup_user_with_immich(client)
        trip = _create_trip(client)
        _store_album_id(trip["id"], "deleted-album")

        with patch(
            "backend.integrations.immich.client.album_exists", new=AsyncMock(return_value=False)
        ):
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
        _store_album_id(trip["id"], "some-album")

        resp = client.get(f"/api/trips/{trip['id']}/immich-album/status")
        assert resp.status_code == 200
        assert resp.json()["exists"] is True
