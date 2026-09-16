"""
Black-box tests for the trash: delete → list → restore / purge, and the one
property the trash exists for — a deleted booking can be re-imported.

Flights are created through /api/sync/upload-eml with GDS compact receipts
written in bare IATA codes, so the source mail's unique key is exercised the
way a real sync exercises it.
"""

import io

from fastapi.testclient import TestClient


def _receipt(ref: str, legs: list[str]) -> bytes:
    body = "ELECTRONIC TICKET RECEIPT\nBOOKING REF: " + ref + "\n" + "\n".join(legs) + "\n"
    return (
        "From: tickets@example.com\r\nTo: t@example.com\r\nSubject: Electronic ticket receipt\r\n"
        "Date: Mon, 04 Jan 2027 10:00:00 +0000\r\nMessage-ID: <" + ref + "@example.com>\r\n"
        "MIME-Version: 1.0\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n" + body
    ).encode()


def _seed_airports(api_app):
    from backend.database import db_write
    from backend.parsers.shared import is_valid_iata, resolve_iata

    with db_write() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO airports (iata_code, name, city_name, country_code) VALUES (?,?,?,?)",
            [("ARN", "Stockholm Arlanda", "Stockholm", "SE"), ("LIS", "Lisbon", "Lisbon", "PT")],
        )
    is_valid_iata.cache_clear()
    resolve_iata.cache_clear()


def _upload(client: TestClient, ref: str, legs: list[str]):
    r = client.post(
        "/api/sync/upload-eml",
        files={"files": (f"{ref}.eml", io.BytesIO(_receipt(ref, legs)), "message/rfc822")},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _flights_for(client: TestClient, ref: str) -> list[dict]:
    rows = client.get("/api/flights?limit=500").json()["flights"]
    return [f for f in rows if f["booking_reference"] == ref]


def _trip_of(client: TestClient, ref: str) -> str:
    (flight,) = _flights_for(client, ref)
    assert flight["trip_id"]
    return flight["trip_id"]


class TestTripToTrash:
    def test_deleting_a_trip_lists_it_in_the_trash_with_its_contents(self, auth_client, api_app):
        _seed_airports(api_app)
        _upload(auth_client, "TRASH1", ["TP 783 / 10MAR ARN - LIS 19:05 22:35"])
        trip_id = _trip_of(auth_client, "TRASH1")
        auth_client.post(f"/api/trips/{trip_id}/rating", json={"rating": 4.5})
        auth_client.put(f"/api/trips/{trip_id}/note", json={"note": "lovely"})

        assert auth_client.delete(f"/api/trips/{trip_id}").status_code == 204
        assert auth_client.get(f"/api/trips/{trip_id}").status_code == 404
        assert _flights_for(auth_client, "TRASH1") == []

        (item,) = [i for i in auth_client.get("/api/trash").json() if i["entity_id"] == trip_id]
        assert item["kind"] == "trip"
        assert item["summary"]["flight_count"] == 1
        assert item["summary"]["has_notes"] is True

    def test_restore_brings_the_trip_its_flights_and_its_notes_back(self, auth_client, api_app):
        _seed_airports(api_app)
        _upload(auth_client, "TRASH2", ["TP 783 / 11MAR ARN - LIS 19:05 22:35"])
        trip_id = _trip_of(auth_client, "TRASH2")
        auth_client.put(f"/api/trips/{trip_id}/note", json={"note": "keep me"})
        auth_client.delete(f"/api/trips/{trip_id}")
        (item,) = [i for i in auth_client.get("/api/trash").json() if i["entity_id"] == trip_id]

        r = auth_client.post(f"/api/trash/{item['id']}/restore")
        assert r.status_code == 200, r.text
        assert r.json()["restored"]["trips"] == 1
        assert r.json()["restored"]["flights"] == 1
        assert auth_client.get(f"/api/trips/{trip_id}").json()["note"] == "keep me"
        assert len(_flights_for(auth_client, "TRASH2")) == 1
        assert [i for i in auth_client.get("/api/trash").json() if i["entity_id"] == trip_id] == []

    def test_a_deleted_booking_can_be_imported_again(self, auth_client, api_app):
        """The reason the delete is a real delete: a mis-parsed booking is deleted
        and re-imported, and the same mail produces fresh rows."""
        _seed_airports(api_app)
        _upload(auth_client, "TRASH3", ["TP 783 / 12MAR ARN - LIS 19:05 22:35"])
        trip_id = _trip_of(auth_client, "TRASH3")
        auth_client.delete(f"/api/trips/{trip_id}")

        result = _upload(auth_client, "TRASH3", ["TP 783 / 12MAR ARN - LIS 19:05 22:35"])
        assert result["flights_created"] == 1
        assert len(_flights_for(auth_client, "TRASH3")) == 1

    def test_restoring_over_a_re_import_skips_what_is_already_live(self, auth_client, api_app):
        _seed_airports(api_app)
        _upload(auth_client, "TRASH4", ["TP 783 / 13MAR ARN - LIS 19:05 22:35"])
        trip_id = _trip_of(auth_client, "TRASH4")
        auth_client.delete(f"/api/trips/{trip_id}")
        _upload(auth_client, "TRASH4", ["TP 783 / 13MAR ARN - LIS 19:05 22:35"])
        (item,) = [i for i in auth_client.get("/api/trash").json() if i["entity_id"] == trip_id]

        r = auth_client.post(f"/api/trash/{item['id']}/restore").json()
        assert r["skipped"].get("flights") == 1
        assert len(_flights_for(auth_client, "TRASH4")) == 1

    def test_purge_removes_the_entry_for_good(self, auth_client, api_app):
        _seed_airports(api_app)
        _upload(auth_client, "TRASH5", ["TP 783 / 14MAR ARN - LIS 19:05 22:35"])
        trip_id = _trip_of(auth_client, "TRASH5")
        auth_client.delete(f"/api/trips/{trip_id}")
        (item,) = [i for i in auth_client.get("/api/trash").json() if i["entity_id"] == trip_id]
        assert auth_client.delete(f"/api/trash/{item['id']}").status_code == 204
        assert auth_client.post(f"/api/trash/{item['id']}/restore").status_code == 404

    def test_another_user_cannot_see_or_restore_it(self, auth_client, api_app):
        import bcrypt

        _seed_airports(api_app)
        _upload(auth_client, "TRASH6", ["TP 783 / 15MAR ARN - LIS 19:05 22:35"])
        trip_id = _trip_of(auth_client, "TRASH6")
        auth_client.delete(f"/api/trips/{trip_id}")
        (item,) = [i for i in auth_client.get("/api/trash").json() if i["entity_id"] == trip_id]

        from backend.database import db_write

        with db_write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (username, password_hash, is_admin) VALUES (?, ?, 0)",
                ("trash_other", bcrypt.hashpw(b"pass1234", bcrypt.gensalt()).decode()),
            )
        other = TestClient(api_app, raise_server_exceptions=True, base_url="https://testserver")
        assert (
            other.post(
                "/api/auth/login", json={"username": "trash_other", "password": "pass1234"}
            ).status_code
            == 200
        )
        assert other.get("/api/trash").json() == []
        assert other.post(f"/api/trash/{item['id']}/restore").status_code == 404

    def test_unauthenticated(self, client):
        assert client.get("/api/trash").status_code == 401


class TestFlightToTrash:
    def test_a_deleted_flight_is_restorable(self, auth_client, api_app):
        _seed_airports(api_app)
        _upload(auth_client, "TRASH7", ["TP 783 / 16MAR ARN - LIS 19:05 22:35"])
        (flight,) = _flights_for(auth_client, "TRASH7")
        assert auth_client.delete(f"/api/flights/{flight['id']}").status_code in (200, 204)
        assert _flights_for(auth_client, "TRASH7") == []
        (item,) = [
            i for i in auth_client.get("/api/trash").json() if i["entity_id"] == flight["id"]
        ]
        assert item["kind"] == "flight" and item["label"].startswith("TP783")
        r = auth_client.post(f"/api/trash/{item['id']}/restore")
        assert r.status_code == 200 and r.json()["restored"]["flights"] == 1
        assert _flights_for(auth_client, "TRASH7")[0]["trip_id"] == flight["trip_id"]

    def test_restored_into_a_trip_that_is_gone_comes_back_ungrouped(self, auth_client, api_app):
        _seed_airports(api_app)
        _upload(auth_client, "TRASH8", ["TP 783 / 17MAR ARN - LIS 19:05 22:35"])
        (flight,) = _flights_for(auth_client, "TRASH8")
        auth_client.delete(f"/api/flights/{flight['id']}")
        auth_client.delete(f"/api/trips/{flight['trip_id']}")
        (item,) = [
            i for i in auth_client.get("/api/trash").json() if i["entity_id"] == flight["id"]
        ]
        assert auth_client.post(f"/api/trash/{item['id']}/restore").status_code == 200
        assert _flights_for(auth_client, "TRASH8")[0]["trip_id"] is None


class TestActivityLog:
    def test_records_the_whole_story(self, auth_client, api_app):
        _seed_airports(api_app)
        _upload(auth_client, "TRASH9", ["TP 783 / 18MAR ARN - LIS 19:05 22:35"])
        trip_id = _trip_of(auth_client, "TRASH9")
        auth_client.delete(f"/api/trips/{trip_id}")
        (item,) = [i for i in auth_client.get("/api/trash").json() if i["entity_id"] == trip_id]
        auth_client.post(f"/api/trash/{item['id']}/restore")
        auth_client.post("/api/sync/full-sync")

        actions = [e["action"] for e in auth_client.get("/api/activity").json()]
        assert actions[:3] == ["sync.full", "trip.restored", "trip.trashed"]
        entry = next(
            e for e in auth_client.get("/api/activity").json() if e["action"] == "trip.trashed"
        )
        assert entry["entity_id"] == trip_id and entry["details"]["flight_count"] == 1

    def test_unauthenticated(self, client):
        assert client.get("/api/activity").status_code == 401
