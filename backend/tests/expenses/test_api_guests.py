"""Tests for the guests endpoints."""


class TestListGuests:
    def test_empty_for_new_user(self, auth_client):
        r = auth_client.get("/api/guests")
        assert r.status_code == 200
        assert r.json() == []

    def test_unauthenticated_returns_401(self, client):
        r = client.get("/api/guests")
        assert r.status_code == 401


class TestCreateGuest:
    def test_create_basic(self, auth_client):
        r = auth_client.post("/api/guests", json={"name": "Grandma"})
        assert r.status_code == 201
        data = r.json()
        assert data["ok"] is True
        assert "id" in data

    def test_appears_in_list(self, auth_client):
        auth_client.post("/api/guests", json={"name": "Grandma"})
        guests = auth_client.get("/api/guests").json()
        assert len(guests) == 1
        assert guests[0]["name"] == "Grandma"

    def test_blank_name_rejected(self, auth_client):
        r = auth_client.post("/api/guests", json={"name": "   "})
        assert r.status_code == 400


class TestUpdateGuest:
    def test_rename(self, auth_client):
        guest_id = auth_client.post("/api/guests", json={"name": "Grandma"}).json()["id"]
        r = auth_client.patch(f"/api/guests/{guest_id}", json={"name": "Grandpa"})
        assert r.status_code == 200
        assert r.json()["name"] == "Grandpa"
        guests = auth_client.get("/api/guests").json()
        assert guests[0]["name"] == "Grandpa"

    def test_blank_name_rejected(self, auth_client):
        guest_id = auth_client.post("/api/guests", json={"name": "Grandma"}).json()["id"]
        r = auth_client.patch(f"/api/guests/{guest_id}", json={"name": "   "})
        assert r.status_code == 400

    def test_rename_nonexistent_returns_404(self, auth_client):
        r = auth_client.patch("/api/guests/999999", json={"name": "Grandpa"})
        assert r.status_code == 404

    def test_unauthenticated_returns_401(self, client):
        r = client.patch("/api/guests/1", json={"name": "Grandpa"})
        assert r.status_code == 401


class TestDeleteGuest:
    def test_delete_unused_guest(self, auth_client):
        guest_id = auth_client.post("/api/guests", json={"name": "Grandma"}).json()["id"]
        r = auth_client.delete(f"/api/guests/{guest_id}")
        assert r.status_code == 204
        assert auth_client.get("/api/guests").json() == []

    def test_delete_nonexistent_returns_404(self, auth_client):
        r = auth_client.delete("/api/guests/999999")
        assert r.status_code == 404

    def test_delete_used_guest_returns_400(self, auth_client):
        guest_id = auth_client.post("/api/guests", json={"name": "Grandma"}).json()["id"]
        trip_id = auth_client.post("/api/trips", json={"name": "Trip"}).json()["id"]
        auth_client.post(
            f"/api/trips/{trip_id}/expenses",
            json={
                "description": "Cab",
                "amount": 30.0,
                "currency": "EUR",
                "paid_by": {"type": "guest", "id": guest_id},
            },
        )
        r = auth_client.delete(f"/api/guests/{guest_id}")
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert detail["error"] == "guest_in_use"
        assert detail["params"] == {"name": "Grandma", "count": 1}
        assert detail["message"] == "Guest Grandma is used in 1 existing expense(s)"
