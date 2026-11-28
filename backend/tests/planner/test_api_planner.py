"""Black-box tests for the trip organizer API (/api/trips/{id}/plan)."""

import bcrypt
from fastapi.testclient import TestClient


def _make_user(api_app, username: str, password: str = "pass1234") -> TestClient:
    from backend.database import db_write

    with db_write() as conn:
        ph = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        conn.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, is_admin) VALUES (?, ?, 0)",
            (username, ph),
        )
    c = TestClient(api_app, raise_server_exceptions=True, base_url="https://testserver")
    assert (
        c.post("/api/auth/login", json={"username": username, "password": password}).status_code
        == 200
    )
    return c


def _trip(client, name="China") -> str:
    return client.post("/api/trips", json={"name": name}).json()["id"]


def _plan(client, trip_id):
    r = client.get(f"/api/trips/{trip_id}/plan")
    assert r.status_code == 200
    return r.json()


STOP = {
    "name": "Beijing",
    "start_date": "2027-03-24",
    "end_date": "2027-03-27",
    "country_code": "cn",
}


class TestAccess:
    def test_empty_plan(self, auth_client):
        assert _plan(auth_client, _trip(auth_client)) == {"stops": [], "items": [], "tasks": []}

    def test_unauthenticated(self, client):
        assert client.get("/api/trips/x/plan").status_code == 401

    def test_other_users_trip_is_not_found(self, auth_client, api_app):
        trip_id = _trip(auth_client)
        other = _make_user(api_app, "plan_other")
        assert other.get(f"/api/trips/{trip_id}/plan").status_code == 404
        assert (
            other.post(f"/api/trips/{trip_id}/plan/items", json={"title": "x"}).status_code == 404
        )


class TestStops:
    def test_a_stop_is_listed_and_becomes_a_destination(self, auth_client):
        trip_id = _trip(auth_client)
        r = auth_client.post(f"/api/trips/{trip_id}/plan/stops", json=STOP)
        assert r.status_code == 201
        (stop,) = _plan(auth_client, trip_id)["stops"]
        assert stop["name"] == "Beijing" and stop["country_code"] == "CN"
        trip = auth_client.get(f"/api/trips/{trip_id}").json()
        assert [d["name"] for d in trip["destinations"]] == ["Beijing"]

    def test_an_existing_destination_is_not_duplicated(self, auth_client):
        trip_id = _trip(auth_client)
        auth_client.post(f"/api/trips/{trip_id}/plan/stops", json=STOP)
        auth_client.post(
            f"/api/trips/{trip_id}/plan/stops",
            json={**STOP, "name": "beijing", "start_date": "2027-04-07", "end_date": "2027-04-08"},
        )
        trip = auth_client.get(f"/api/trips/{trip_id}").json()
        assert len(trip["destinations"]) == 1

    def test_end_before_start_is_refused(self, auth_client):
        trip_id = _trip(auth_client)
        r = auth_client.post(
            f"/api/trips/{trip_id}/plan/stops", json={**STOP, "end_date": "2027-03-20"}
        )
        assert r.status_code == 400

    def test_update_and_delete(self, auth_client):
        trip_id = _trip(auth_client)
        stop_id = auth_client.post(f"/api/trips/{trip_id}/plan/stops", json=STOP).json()["id"]
        r = auth_client.patch(
            f"/api/trips/{trip_id}/plan/stops/{stop_id}", json={"end_date": "2027-03-28"}
        )
        assert r.status_code == 204
        assert _plan(auth_client, trip_id)["stops"][0]["end_date"] == "2027-03-28"
        bad = auth_client.patch(
            f"/api/trips/{trip_id}/plan/stops/{stop_id}", json={"start_date": "2027-04-01"}
        )
        assert bad.status_code == 400
        assert auth_client.delete(f"/api/trips/{trip_id}/plan/stops/{stop_id}").status_code == 204
        assert _plan(auth_client, trip_id)["stops"] == []
        # The destination is the traveller's and stays.
        assert len(auth_client.get(f"/api/trips/{trip_id}").json()["destinations"]) == 1


class TestItems:
    def test_items_by_day_and_ideas(self, auth_client):
        trip_id = _trip(auth_client)
        base = f"/api/trips/{trip_id}/plan/items"
        auth_client.post(base, json={"title": "Cidade proibida", "date": "2027-03-24"})
        auth_client.post(base, json={"title": "Muralha", "date": "2027-03-24", "time": "07:20"})
        auth_client.post(base, json={"title": "Uniqlo t-shirts"})
        items = _plan(auth_client, trip_id)["items"]
        assert [i["title"] for i in items] == ["Cidade proibida", "Muralha", "Uniqlo t-shirts"]
        assert [i["sort_order"] for i in items] == [0, 1, 0]
        assert items[2]["date"] is None and items[0]["status"] == "idea"

    def test_moving_an_item_to_another_day_and_back_to_ideas(self, auth_client):
        trip_id = _trip(auth_client)
        base = f"/api/trips/{trip_id}/plan/items"
        item_id = auth_client.post(base, json={"title": "Pandas", "date": "2027-03-29"}).json()[
            "id"
        ]
        assert (
            auth_client.patch(
                f"{base}/{item_id}", json={"date": "2027-03-30", "status": "booked"}
            ).status_code
            == 204
        )
        (item,) = _plan(auth_client, trip_id)["items"]
        assert (item["date"], item["status"]) == ("2027-03-30", "booked")
        auth_client.patch(f"{base}/{item_id}", json={"date": None})
        assert _plan(auth_client, trip_id)["items"][0]["date"] is None

    def test_a_patch_without_date_leaves_it(self, auth_client):
        trip_id = _trip(auth_client)
        base = f"/api/trips/{trip_id}/plan/items"
        item_id = auth_client.post(base, json={"title": "Hot pot", "date": "2027-03-30"}).json()[
            "id"
        ]
        auth_client.patch(f"{base}/{item_id}", json={"title": "Book hot pot"})
        (item,) = _plan(auth_client, trip_id)["items"]
        assert (item["title"], item["date"]) == ("Book hot pot", "2027-03-30")

    def test_validation(self, auth_client):
        trip_id = _trip(auth_client)
        base = f"/api/trips/{trip_id}/plan/items"
        assert auth_client.post(base, json={"title": "  "}).status_code == 400
        assert auth_client.post(base, json={"title": "x", "status": "maybe"}).status_code == 400
        assert auth_client.post(base, json={"title": "x", "date": "2027-02-30"}).status_code == 400
        assert auth_client.post(base, json={"title": "x", "time": "7h"}).status_code == 422
        assert auth_client.patch(f"{base}/nope", json={"title": "x"}).status_code == 404

    def test_delete(self, auth_client):
        trip_id = _trip(auth_client)
        base = f"/api/trips/{trip_id}/plan/items"
        item_id = auth_client.post(base, json={"title": "x"}).json()["id"]
        assert auth_client.delete(f"{base}/{item_id}").status_code == 204
        assert auth_client.delete(f"{base}/{item_id}").status_code == 404


class TestTasks:
    def test_task_with_assignee_and_done(self, auth_client):
        trip_id = _trip(auth_client)
        me = auth_client.get("/api/auth/me").json()["id"]
        base = f"/api/trips/{trip_id}/plan/tasks"
        task_id = auth_client.post(
            base, json={"text": "eSIM", "assignee_type": "user", "assignee_id": me}
        ).json()["id"]
        auth_client.patch(f"{base}/{task_id}", json={"done": True})
        (task,) = _plan(auth_client, trip_id)["tasks"]
        assert task == {
            "id": task_id,
            "text": "eSIM",
            "done": True,
            "assignee_type": "user",
            "assignee_id": me,
            "sort_order": 0,
        }
        auth_client.patch(f"{base}/{task_id}", json={"assignee_type": None, "assignee_id": None})
        assert _plan(auth_client, trip_id)["tasks"][0]["assignee_id"] is None

    def test_someone_off_the_trip_cannot_be_assigned(self, auth_client, api_app):
        trip_id = _trip(auth_client)
        _make_user(api_app, "plan_stranger")
        from backend.database import db_conn

        with db_conn() as conn:
            stranger = conn.execute(
                "SELECT id FROM users WHERE username = 'plan_stranger'"
            ).fetchone()["id"]
        r = auth_client.post(
            f"/api/trips/{trip_id}/plan/tasks",
            json={"text": "VPN", "assignee_type": "user", "assignee_id": stranger},
        )
        assert r.status_code == 400

    def test_delete(self, auth_client):
        trip_id = _trip(auth_client)
        base = f"/api/trips/{trip_id}/plan/tasks"
        task_id = auth_client.post(base, json={"text": "VPN"}).json()["id"]
        assert auth_client.delete(f"{base}/{task_id}").status_code == 204
        assert _plan(auth_client, trip_id)["tasks"] == []


class TestTripDeletion:
    def test_deleting_the_trip_takes_the_plan(self, auth_client):
        trip_id = _trip(auth_client)
        auth_client.post(f"/api/trips/{trip_id}/plan/items", json={"title": "x"})
        auth_client.delete(f"/api/trips/{trip_id}")
        from backend.database import db_conn

        with db_conn() as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM trip_plan_items WHERE trip_id = ?", (trip_id,)
            ).fetchone()[0]
        assert n == 0


class TestItemPlace:
    def test_an_item_carries_a_place_for_the_map(self, auth_client):
        trip_id = _trip(auth_client)
        base = f"/api/trips/{trip_id}/plan/items"
        item_id = auth_client.post(
            base,
            json={
                "title": "Cidade Proibida",
                "place_name": "Forbidden City",
                "lat": 39.916,
                "lon": 116.397,
            },
        ).json()["id"]
        (item,) = _plan(auth_client, trip_id)["items"]
        assert (item["place_name"], item["lat"], item["lon"]) == ("Forbidden City", 39.916, 116.397)
        auth_client.patch(f"{base}/{item_id}", json={"place_name": None, "lat": None, "lon": None})
        assert _plan(auth_client, trip_id)["items"][0]["lat"] is None


class TestItemPhoto:
    THUMB = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Tower.jpg/320px-Tower.jpg"
    PAGE = "https://en.wikipedia.org/wiki/Bel%C3%A9m_Tower"

    def test_a_suggested_place_keeps_its_photo(self, auth_client):
        trip_id = _trip(auth_client)
        r = auth_client.post(
            f"/api/trips/{trip_id}/plan/items",
            json={"title": "Belém Tower", "image_url": self.THUMB, "image_page": self.PAGE},
        )
        assert r.status_code in (200, 201), r.text
        item = _plan(auth_client, trip_id)["items"][0]
        assert item["image_url"] == self.THUMB and item["image_page"] == self.PAGE

    def test_a_photo_from_anywhere_else_is_refused(self, auth_client):
        trip_id = _trip(auth_client)
        r = auth_client.post(
            f"/api/trips/{trip_id}/plan/items",
            json={"title": "X", "image_url": "https://tracker.example/pixel.gif"},
        )
        assert r.status_code in (400, 422)
        r = auth_client.post(
            f"/api/trips/{trip_id}/plan/items",
            json={"title": "X", "image_url": self.THUMB, "image_page": "https://evil.example/"},
        )
        assert r.status_code in (400, 422)

    def test_the_photo_can_be_removed(self, auth_client):
        trip_id = _trip(auth_client)
        item_id = auth_client.post(
            f"/api/trips/{trip_id}/plan/items", json={"title": "T", "image_url": self.THUMB}
        ).json()["id"]
        auth_client.patch(f"/api/trips/{trip_id}/plan/items/{item_id}", json={"image_url": None})
        assert _plan(auth_client, trip_id)["items"][0]["image_url"] is None
