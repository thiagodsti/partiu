"""Tests for the trip segments and station-search endpoints."""

from unittest.mock import patch

import bcrypt
from fastapi.testclient import TestClient

from backend.tests.segments.conftest import segment_payload


def _make_user(api_app, username: str, password: str = "pass1234") -> TestClient:
    with __import__("backend.database", fromlist=["db_write"]).db_write() as conn:
        ph = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        conn.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, is_admin) VALUES (?, ?, 0)",
            (username, ph),
        )
    c = TestClient(api_app, raise_server_exceptions=True, base_url="https://testserver")
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return c


def _trip(client: TestClient, name: str = "China 2026") -> str:
    return client.post("/api/trips", json={"name": name}).json()["id"]


class TestListSegments:
    def test_empty_for_new_trip(self, auth_client):
        trip_id = _trip(auth_client)
        r = auth_client.get(f"/api/trips/{trip_id}/segments")
        assert r.status_code == 200
        assert r.json() == []

    def test_unauthenticated_returns_401(self, client):
        assert client.get("/api/trips/nope/segments").status_code == 401

    def test_unknown_trip_returns_404(self, auth_client):
        assert auth_client.get("/api/trips/does-not-exist/segments").status_code == 404

    def test_other_users_trip_returns_404(self, auth_client, api_app):
        trip_id = _trip(auth_client, "Private")
        other = _make_user(api_app, "seg_other1")
        assert other.get(f"/api/trips/{trip_id}/segments").status_code == 404


class TestCreateSegment:
    def test_create_returns_201_and_stores_utc(self, auth_client):
        trip_id = _trip(auth_client)
        r = auth_client.post(f"/api/trips/{trip_id}/segments", json=segment_payload())
        assert r.status_code == 201
        assert r.json()["ok"] is True

        segment = auth_client.get(f"/api/trips/{trip_id}/segments").json()[0]
        assert segment["type"] == "train"
        assert segment["operator"] == "China Railway"
        assert segment["departure"]["name"] == "Beijing West Railway Station"
        assert segment["departure"]["timezone"] == "Asia/Shanghai"
        assert segment["departure_datetime"].startswith("2026-10-04T00:00:00")
        assert segment["duration_minutes"] == 270

    def test_invalid_type_returns_400(self, auth_client):
        trip_id = _trip(auth_client)
        r = auth_client.post(
            f"/api/trips/{trip_id}/segments", json=segment_payload(type="teleport")
        )
        assert r.status_code == 400

    def test_arrival_before_departure_returns_400(self, auth_client):
        trip_id = _trip(auth_client)
        r = auth_client.post(
            f"/api/trips/{trip_id}/segments",
            json=segment_payload(arrival_datetime="2026-10-04T07:00"),
        )
        assert r.status_code == 400

    def test_empty_place_name_is_rejected_by_the_schema(self, auth_client):
        trip_id = _trip(auth_client)
        r = auth_client.post(
            f"/api/trips/{trip_id}/segments", json=segment_payload(departure={"name": ""})
        )
        assert r.status_code == 422

    def test_out_of_range_coordinates_are_rejected(self, auth_client):
        trip_id = _trip(auth_client)
        r = auth_client.post(
            f"/api/trips/{trip_id}/segments",
            json=segment_payload(departure={"name": "Nowhere", "lat": 120.0, "lon": 0.0}),
        )
        assert r.status_code == 422

    def test_other_users_trip_returns_404(self, auth_client, api_app):
        trip_id = _trip(auth_client, "Private")
        other = _make_user(api_app, "seg_other2")
        r = other.post(f"/api/trips/{trip_id}/segments", json=segment_payload())
        assert r.status_code == 404


class TestUpdateSegment:
    def test_patch_one_field_keeps_the_rest(self, auth_client):
        trip_id = _trip(auth_client)
        segment_id = auth_client.post(
            f"/api/trips/{trip_id}/segments", json=segment_payload()
        ).json()["id"]

        r = auth_client.patch(
            f"/api/trips/{trip_id}/segments/{segment_id}", json={"seat": "Car 8, 4F"}
        )
        assert r.status_code == 200

        segment = auth_client.get(f"/api/trips/{trip_id}/segments").json()[0]
        assert segment["seat"] == "Car 8, 4F"
        assert segment["operator"] == "China Railway"
        assert segment["number"] == "G87"

    def test_unknown_segment_returns_404(self, auth_client):
        trip_id = _trip(auth_client)
        r = auth_client.patch(f"/api/trips/{trip_id}/segments/nope", json={"seat": "1A"})
        assert r.status_code == 404

    def test_other_users_segment_returns_404(self, auth_client, api_app):
        trip_id = _trip(auth_client, "Private")
        segment_id = auth_client.post(
            f"/api/trips/{trip_id}/segments", json=segment_payload()
        ).json()["id"]
        other = _make_user(api_app, "seg_other3")
        r = other.patch(f"/api/trips/{trip_id}/segments/{segment_id}", json={"seat": "1A"})
        assert r.status_code == 404


class TestDeleteSegment:
    def test_delete_removes_it(self, auth_client):
        trip_id = _trip(auth_client)
        segment_id = auth_client.post(
            f"/api/trips/{trip_id}/segments", json=segment_payload()
        ).json()["id"]

        assert auth_client.delete(f"/api/trips/{trip_id}/segments/{segment_id}").status_code == 200
        assert auth_client.get(f"/api/trips/{trip_id}/segments").json() == []

    def test_unknown_segment_returns_404(self, auth_client):
        trip_id = _trip(auth_client)
        assert auth_client.delete(f"/api/trips/{trip_id}/segments/nope").status_code == 404

    def test_other_users_segment_returns_404(self, auth_client, api_app):
        trip_id = _trip(auth_client, "Private")
        segment_id = auth_client.post(
            f"/api/trips/{trip_id}/segments", json=segment_payload()
        ).json()["id"]
        other = _make_user(api_app, "seg_other4")
        assert other.delete(f"/api/trips/{trip_id}/segments/{segment_id}").status_code == 404


class TestStationSearch:
    """The endpoint is a thin pass-through; the client's own parsing is covered
    in test_photon_client.py, so these cover the HTTP contract only."""

    def test_requires_authentication(self, client):
        assert client.get("/api/stations/search?q=beijing").status_code == 401

    def test_returns_stations(self, auth_client):
        stations = [
            {
                "name": "Beijing West Railway Station",
                "city": "Beijing",
                "country": "China",
                "countrycode": "CN",
                "lat": 39.8936695,
                "lon": 116.3151027,
                "osm_id": 123,
            }
        ]
        with patch("backend.segments.routes.photon.search_stations", return_value=stations):
            r = auth_client.get("/api/stations/search?q=beijing west&kind=train")

        assert r.status_code == 200
        body = r.json()
        assert len(body) == 1
        assert body[0]["name"] == "Beijing West Railway Station"
        # osm_id is an internal detail and is not part of the response contract.
        assert "osm_id" not in body[0]

    def test_geocoder_failure_returns_empty_list_not_an_error(self, auth_client):
        """An unreachable geocoder must degrade to free-text entry in the UI,
        so the endpoint answers 200 with [] rather than 5xx."""
        with patch("backend.segments.routes.photon.search_stations", return_value=[]):
            r = auth_client.get("/api/stations/search?q=whatever")

        assert r.status_code == 200
        assert r.json() == []
