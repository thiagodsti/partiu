"""Black-box tests for the trip stays endpoints."""

import bcrypt
from fastapi.testclient import TestClient

from backend.tests.stays.conftest import stay_payload


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


def _trip(client: TestClient, name: str = "Portugal 2026") -> str:
    return client.post("/api/trips", json={"name": name}).json()["id"]


class TestListStays:
    def test_empty_for_new_trip(self, auth_client):
        trip_id = _trip(auth_client)
        r = auth_client.get(f"/api/trips/{trip_id}/stays")
        assert r.status_code == 200
        assert r.json() == []

    def test_unauthenticated_returns_401(self, client):
        assert client.get("/api/trips/nope/stays").status_code == 401

    def test_unknown_trip_returns_404(self, auth_client):
        assert auth_client.get("/api/trips/does-not-exist/stays").status_code == 404

    def test_other_users_trip_returns_404(self, auth_client, api_app):
        trip_id = _trip(auth_client, "Private")
        other = _make_user(api_app, "stay_other1")
        assert other.get(f"/api/trips/{trip_id}/stays").status_code == 404


class TestCreateStay:
    def test_create_returns_201_and_stores_local_dates(self, auth_client):
        trip_id = _trip(auth_client)
        r = auth_client.post(f"/api/trips/{trip_id}/stays", json=stay_payload())
        assert r.status_code == 201
        assert r.json()["ok"] is True

        stay = auth_client.get(f"/api/trips/{trip_id}/stays").json()[0]
        assert stay["kind"] == "hotel"
        assert stay["place"]["name"] == "Hotel Avenida Palace"
        assert stay["place"]["timezone"] == "Europe/Lisbon"
        assert stay["check_in_date"] == "2026-10-04"
        assert stay["check_out_date"] == "2026-10-08"
        assert stay["nights"] == 4
        assert stay["guests"] == 2

    def test_create_widens_the_trip_span(self, auth_client):
        trip_id = _trip(auth_client)
        auth_client.post(f"/api/trips/{trip_id}/stays", json=stay_payload())

        trip = auth_client.get(f"/api/trips/{trip_id}").json()
        assert trip["start_date"] == "2026-10-04"
        assert trip["end_date"] == "2026-10-08"

    def test_airbnb_without_coordinates_is_accepted(self, auth_client):
        trip_id = _trip(auth_client)
        r = auth_client.post(
            f"/api/trips/{trip_id}/stays",
            json=stay_payload(kind="airbnb", place={"name": "Flat in Alfama"}),
        )
        assert r.status_code == 201

        stay = auth_client.get(f"/api/trips/{trip_id}/stays").json()[0]
        assert stay["place"]["lat"] is None
        assert stay["place"]["timezone"] is None

    def test_checkout_before_checkin_returns_400(self, auth_client):
        trip_id = _trip(auth_client)
        r = auth_client.post(
            f"/api/trips/{trip_id}/stays",
            json=stay_payload(
                check_in_datetime="2026-10-08T15:00", check_out_datetime="2026-10-04T11:00"
            ),
        )
        assert r.status_code == 400
        assert "after check-in" in r.json()["detail"]

    def test_unknown_kind_returns_400(self, auth_client):
        trip_id = _trip(auth_client)
        r = auth_client.post(f"/api/trips/{trip_id}/stays", json=stay_payload(kind="castle"))
        assert r.status_code == 400

    def test_blank_name_returns_422(self, auth_client):
        """Caught by the DTO's min_length before the service ever runs."""
        trip_id = _trip(auth_client)
        r = auth_client.post(f"/api/trips/{trip_id}/stays", json=stay_payload(place={"name": ""}))
        assert r.status_code == 422

    def test_other_users_trip_returns_404(self, auth_client, api_app):
        trip_id = _trip(auth_client, "Private")
        other = _make_user(api_app, "stay_other2")
        assert other.post(f"/api/trips/{trip_id}/stays", json=stay_payload()).status_code == 404

    def test_a_stay_outside_the_flight_dates_is_accepted(self, auth_client):
        """The airport hotel booked for the night before an early departure is
        outside the trip's existing span and must extend it, not be refused."""
        trip_id = _trip(auth_client)
        auth_client.post(
            f"/api/trips/{trip_id}/stays",
            json=stay_payload(
                check_in_datetime="2026-10-01T22:00", check_out_datetime="2026-10-02T06:00"
            ),
        )
        r = auth_client.post(f"/api/trips/{trip_id}/stays", json=stay_payload())
        assert r.status_code == 201

        trip = auth_client.get(f"/api/trips/{trip_id}").json()
        assert trip["start_date"] == "2026-10-01"
        assert trip["end_date"] == "2026-10-08"


class TestUpdateStay:
    def test_patch_one_field_keeps_the_rest(self, auth_client):
        trip_id = _trip(auth_client)
        stay_id = auth_client.post(f"/api/trips/{trip_id}/stays", json=stay_payload()).json()["id"]

        r = auth_client.patch(f"/api/trips/{trip_id}/stays/{stay_id}", json={"room_type": "Twin"})
        assert r.status_code == 200

        stay = auth_client.get(f"/api/trips/{trip_id}/stays").json()[0]
        assert stay["room_type"] == "Twin"
        assert stay["booking_reference"] == "BK12345"
        assert stay["nights"] == 4

    def test_patch_recomputes_the_trip_span(self, auth_client):
        trip_id = _trip(auth_client)
        stay_id = auth_client.post(f"/api/trips/{trip_id}/stays", json=stay_payload()).json()["id"]

        auth_client.patch(
            f"/api/trips/{trip_id}/stays/{stay_id}",
            json={"check_out_datetime": "2026-10-12T11:00"},
        )

        assert auth_client.get(f"/api/trips/{trip_id}").json()["end_date"] == "2026-10-12"

    def test_unknown_stay_returns_404(self, auth_client):
        trip_id = _trip(auth_client)
        r = auth_client.patch(f"/api/trips/{trip_id}/stays/nope", json={"room_type": "Twin"})
        assert r.status_code == 404


class TestDeleteStay:
    def test_delete_removes_it_and_shrinks_the_span(self, auth_client):
        trip_id = _trip(auth_client)
        stay_id = auth_client.post(f"/api/trips/{trip_id}/stays", json=stay_payload()).json()["id"]

        assert auth_client.delete(f"/api/trips/{trip_id}/stays/{stay_id}").status_code == 200
        assert auth_client.get(f"/api/trips/{trip_id}/stays").json() == []
        assert auth_client.get(f"/api/trips/{trip_id}").json()["start_date"] is None

    def test_unknown_stay_returns_404(self, auth_client):
        trip_id = _trip(auth_client)
        assert auth_client.delete(f"/api/trips/{trip_id}/stays/nope").status_code == 404

    def test_other_user_cannot_delete(self, auth_client, api_app):
        trip_id = _trip(auth_client)
        stay_id = auth_client.post(f"/api/trips/{trip_id}/stays", json=stay_payload()).json()["id"]
        other = _make_user(api_app, "stay_other3")

        assert other.delete(f"/api/trips/{trip_id}/stays/{stay_id}").status_code == 404


class TestPlaceSearch:
    def test_returns_accommodation_and_address_candidates(self, auth_client):
        from unittest.mock import patch

        results = [
            {
                "name": "Hotel Avenida Palace",
                "city": "Lisbon",
                "address": "Rua 1º de Dezembro 123, 1200-359, Lisbon",
                "country": "Portugal",
                "countrycode": "PT",
                "category": "place",
                "lat": 38.7145,
                "lon": -9.1409,
                "osm_id": 42,
            },
            {
                "name": "Rua Garrett",
                "city": "Lisbon",
                "address": "Rua Garrett 20, 1200-204, Lisbon",
                "country": "Portugal",
                "countrycode": "PT",
                "category": "address",
                "lat": 38.7108,
                "lon": -9.1409,
                "osm_id": 43,
            },
        ]
        with patch("backend.stays.routes.photon.search_places", return_value=results):
            r = auth_client.get("/api/places/search?q=avenida palace")

        assert r.status_code == 200
        body = r.json()
        assert [x["category"] for x in body] == ["place", "address"]
        # The country code is what makes the stay count toward visited countries.
        assert body[0]["countrycode"] == "PT"
        assert body[0]["address"].startswith("Rua 1º de Dezembro")
        # osm_id is an internal detail and is not part of the response contract.
        assert "osm_id" not in body[0]

    def test_unauthenticated_returns_401(self, client):
        assert client.get("/api/places/search?q=hotel").status_code == 401

    def test_geocoder_failure_returns_empty_list_not_an_error(self, auth_client):
        """An unreachable geocoder must degrade to free-text entry in the UI."""
        from unittest.mock import patch

        with patch("backend.stays.routes.photon.search_places", return_value=[]):
            r = auth_client.get("/api/places/search?q=whatever")

        assert r.status_code == 200
        assert r.json() == []

    def test_create_stores_the_country_from_the_picker(self, auth_client):
        trip_id = _trip(auth_client)
        auth_client.post(f"/api/trips/{trip_id}/stays", json=stay_payload())

        stay = auth_client.get(f"/api/trips/{trip_id}/stays").json()[0]
        assert stay["place"]["country_code"] == "PT"
