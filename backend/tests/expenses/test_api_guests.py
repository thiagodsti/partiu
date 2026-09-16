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


class TestTripGuestRoster:
    """`/api/trips/{id}/guests` — who is on this trip, as opposed to who is in
    your address book. The two were the same thing before migration 0036, which
    is what made a guest created in Settings unusable anywhere."""

    def _trip(self, auth_client) -> str:
        r = auth_client.post("/api/trips", json={"name": "Sardinia"})
        return r.json()["id"]

    def test_a_new_trip_has_no_guests(self, auth_client):
        trip_id = self._trip(auth_client)
        r = auth_client.get(f"/api/trips/{trip_id}/guests")
        assert r.status_code == 200
        assert r.json() == []

    def test_add_then_list(self, auth_client):
        trip_id = self._trip(auth_client)
        guest_id = auth_client.post("/api/guests", json={"name": "Jimmy"}).json()["id"]

        r = auth_client.post(f"/api/trips/{trip_id}/guests", json={"guest_id": guest_id})
        assert r.status_code == 201
        assert r.json()["name"] == "Jimmy"

        assert [g["name"] for g in auth_client.get(f"/api/trips/{trip_id}/guests").json()] == [
            "Jimmy"
        ]

    def test_added_guests_become_pickable_participants(self, auth_client):
        """The bug this feature exists to fix: three guests in the address book
        appeared in no payer select and no split-between list."""
        trip_id = self._trip(auth_client)
        for name in ("Jimmy", "Lucas", "Vivian"):
            guest_id = auth_client.post("/api/guests", json={"name": name}).json()["id"]
            auth_client.post(f"/api/trips/{trip_id}/guests", json={"guest_id": guest_id})

        participants = auth_client.get(f"/api/trips/{trip_id}/expenses/participants").json()
        guests = sorted(p["name"] for p in participants if p["type"] == "guest")
        assert guests == ["Jimmy", "Lucas", "Vivian"]
        # ...and the caller is still in the list, so the picker is you + them.
        assert any(p["type"] == "user" for p in participants)

    def test_the_roster_does_not_leak_to_another_trip(self, auth_client):
        a, b = self._trip(auth_client), self._trip(auth_client)
        guest_id = auth_client.post("/api/guests", json={"name": "Jimmy"}).json()["id"]
        auth_client.post(f"/api/trips/{a}/guests", json={"guest_id": guest_id})

        assert auth_client.get(f"/api/trips/{b}/guests").json() == []
        participants = auth_client.get(f"/api/trips/{b}/expenses/participants").json()
        assert all(p["type"] != "guest" for p in participants)

    def test_remove(self, auth_client):
        trip_id = self._trip(auth_client)
        guest_id = auth_client.post("/api/guests", json={"name": "Jimmy"}).json()["id"]
        auth_client.post(f"/api/trips/{trip_id}/guests", json={"guest_id": guest_id})

        assert auth_client.delete(f"/api/trips/{trip_id}/guests/{guest_id}").status_code == 204
        assert auth_client.get(f"/api/trips/{trip_id}/guests").json() == []
        # The address book keeps them — only this trip's roster changed.
        assert [g["id"] for g in auth_client.get("/api/guests").json()] == [guest_id]

    def test_removing_a_guest_an_expense_names_is_a_conflict(self, auth_client):
        trip_id = self._trip(auth_client)
        guest_id = auth_client.post("/api/guests", json={"name": "Jimmy"}).json()["id"]
        auth_client.post(f"/api/trips/{trip_id}/guests", json={"guest_id": guest_id})
        auth_client.post(
            f"/api/trips/{trip_id}/expenses",
            json={
                "description": "Cab",
                "amount": 30.0,
                "currency": "EUR",
                "paid_by": {"type": "guest", "id": guest_id},
            },
        )

        r = auth_client.delete(f"/api/trips/{trip_id}/guests/{guest_id}")
        assert r.status_code == 409

    def test_unauthenticated(self, client):
        assert client.get("/api/trips/whatever/guests").status_code == 401
