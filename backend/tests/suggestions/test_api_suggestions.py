"""Black-box tests for AI place suggestions (/api/trips/{id}/plan/suggestions).

The model and the geocoder are both mocked: what is under test is what Partiu
sends, what it keeps, and when it refuses — not what a model happens to say.
"""

from unittest.mock import patch

import bcrypt
import pytest
from fastapi.testclient import TestClient

LISBON = (38.7223, -9.1393)

ANSWER = {
    "suggestions": [
        {
            "name": "Time Out Market",
            "why": "Lots of food",
            "category": "food",
            "best_time": "evening",
        },
        {"name": "Mercado da Ribeira", "why": "Same hall", "category": "food", "best_time": "any"},
        {"name": "Tasca do Chico", "why": "Fado", "category": "nightlife", "best_time": "evening"},
        {"name": "Torre de Belém", "why": "Icon", "category": "sight", "best_time": "morning"},
        {"name": "Belém Tower", "why": "Already planned", "category": "sight", "best_time": "any"},
    ]
}


def _hit(name, lat, lon):
    return {"name": name, "lat": lat, "lon": lon, "address": "Lisboa", "city": "Lisboa"}


def fake_search(query, kind=None, limit=8, near=None):
    if kind == "city":
        return [_hit(query, *LISBON)]
    return {
        "Tasca do Chico": [_hit("Tasca do Chico", 38.7115, -9.1440)],
        # A namesake on another continent is not this place.
        "Café Lisboa": [_hit("Café Lisboa", -23.5, -46.6)],
    }.get(query, [])


@pytest.fixture
def ai_on(monkeypatch):
    monkeypatch.setenv("AI_SUGGESTIONS_PROVIDER", "anthropic")
    monkeypatch.setenv("AI_SUGGESTIONS_API_KEY", "test-key")
    with (
        patch("backend.suggestions.service.photon.is_configured", return_value=True),
        # komoot's public instance unless a test says otherwise (a developer's
        # .env may point at a self-hosted one).
        patch("backend.suggestions.service.photon.is_self_hosted", return_value=False),
        patch("backend.suggestions.service.photon.search_places", side_effect=fake_search),
        patch("backend.suggestions.service.complete_json", return_value=ANSWER) as ask,
    ):
        yield ask


def _trip_with_stop(client) -> tuple[str, str]:
    trip_id = client.post(
        "/api/trips",
        json={
            "name": "Lisbon",
            "planned_start_date": "2027-05-10",
            "planned_end_date": "2027-05-14",
        },
    ).json()["id"]
    client.post(
        f"/api/trips/{trip_id}/plan/stops",
        json={"name": "Lisbon", "start_date": "2027-05-10", "end_date": "2027-05-14"},
    )
    stop_id = client.get(f"/api/trips/{trip_id}/plan").json()["stops"][0]["id"]
    return trip_id, stop_id


def _sent(ask) -> dict:
    import json

    return json.loads(ask.call_args.kwargs["user"])


class TestOff:
    def test_not_configured_is_reported_and_refused(self, auth_client, monkeypatch):
        monkeypatch.delenv("AI_SUGGESTIONS_PROVIDER", raising=False)
        assert auth_client.get("/api/suggestions/status").json()["available"] is False
        trip_id, stop_id = _trip_with_stop(auth_client)
        r = auth_client.post(f"/api/trips/{trip_id}/plan/suggestions", json={"stop_id": stop_id})
        assert r.status_code == 404 and r.json()["detail"] == "ai_not_configured"

    def test_a_demo_never_offers_it(self, auth_client, ai_on, monkeypatch):
        monkeypatch.setattr("backend.suggestions.service.settings.DEMO_MODE", True)
        assert auth_client.get("/api/suggestions/status").json()["available"] is False
        trip_id, stop_id = _trip_with_stop(auth_client)
        r = auth_client.post(f"/api/trips/{trip_id}/plan/suggestions", json={"stop_id": stop_id})
        assert r.status_code == 404
        ai_on.assert_not_called()

    def test_a_provider_missing_its_key_is_off(self, auth_client, monkeypatch):
        monkeypatch.setenv("AI_SUGGESTIONS_PROVIDER", "anthropic")
        monkeypatch.delenv("AI_SUGGESTIONS_API_KEY", raising=False)
        with patch("backend.suggestions.service.photon.is_configured", return_value=True):
            assert auth_client.get("/api/suggestions/status").json()["available"] is False


class TestSuggest:
    def test_cards_come_back_without_a_single_map_lookup(self, auth_client, ai_on):
        trip_id, stop_id = _trip_with_stop(auth_client)
        auth_client.post(f"/api/trips/{trip_id}/plan/items", json={"title": "Belém Tower"})
        with patch("backend.suggestions.service.photon.search_places") as search:
            r = auth_client.post(
                f"/api/trips/{trip_id}/plan/suggestions", json={"stop_id": stop_id}
            )
        # The stop has no coordinates, so the city itself is looked up once;
        # the places are not looked up at all.
        assert [c.kwargs.get("kind") for c in search.call_args_list] == ["city"]

        assert r.status_code == 200
        body = r.json()
        by_title = {c["title"]: c for c in body["suggestions"]}
        # The planned one is not repeated; two names for one building are one card.
        assert list(by_title) == ["Time Out Market", "Tasca do Chico", "Torre de Belém"]
        torre = by_title["Torre de Belém"]
        assert torre["on_wikipedia"] and torre["image_url"].endswith("belem.jpg")
        assert (torre["lat"], torre["lon"]) == (38.6916, -9.2160)
        tasca = by_title["Tasca do Chico"]
        assert not tasca["on_wikipedia"] and tasca["lat"] is None

    def test_a_stop_with_coordinates_needs_no_lookup_at_all(self, auth_client, ai_on):
        trip_id = auth_client.post("/api/trips", json={"name": "Lisbon"}).json()["id"]
        auth_client.post(
            f"/api/trips/{trip_id}/plan/stops",
            json={
                "name": "Lisbon",
                "start_date": "2027-05-10",
                "end_date": "2027-05-14",
                "lat": LISBON[0],
                "lon": LISBON[1],
            },
        )
        stop_id = auth_client.get(f"/api/trips/{trip_id}/plan").json()["stops"][0]["id"]
        with patch("backend.suggestions.service.photon.search_places") as search:
            auth_client.post(f"/api/trips/{trip_id}/plan/suggestions", json={"stop_id": stop_id})
        search.assert_not_called()


class TestSelfHostedPhoton:
    def test_every_card_is_put_on_the_map_up_front(self, auth_client, ai_on):
        trip_id, stop_id = _trip_with_stop(auth_client)
        with patch("backend.suggestions.service.photon.is_self_hosted", return_value=True):
            r = auth_client.post(
                f"/api/trips/{trip_id}/plan/suggestions", json={"stop_id": stop_id}
            )
        by_title = {c["title"]: c for c in r.json()["suggestions"]}
        tasca = by_title["Tasca do Chico"]
        assert (tasca["lat"], tasca["lon"]) == (38.7115, -9.1440)
        assert not tasca["on_wikipedia"]

    def test_a_place_the_map_does_not_know_is_still_listed(self, auth_client, ai_on):
        ai_on.return_value = {
            "suggestions": [
                {"name": "Café Lisboa", "why": "x", "category": "food", "best_time": "any"}
            ]
        }
        trip_id, stop_id = _trip_with_stop(auth_client)
        with patch("backend.suggestions.service.photon.is_self_hosted", return_value=True):
            r = auth_client.post(
                f"/api/trips/{trip_id}/plan/suggestions", json={"stop_id": stop_id}
            )
        # The only "Café Lisboa" the map knows is on another continent.
        [card] = r.json()["suggestions"]
        assert card["title"] == "Café Lisboa" and card["lat"] is None


class TestLocate:
    def test_a_picked_place_is_found_on_the_map(self, auth_client, ai_on):
        trip_id, stop_id = _trip_with_stop(auth_client)
        r = auth_client.post(
            f"/api/trips/{trip_id}/plan/suggestions/locate",
            json={"stop_id": stop_id, "name": "Tasca do Chico"},
        )
        assert r.status_code == 200
        assert r.json() == {
            "place_name": "Tasca do Chico",
            "local_name": None,
            "address": "Lisboa",
            "lat": 38.7115,
            "lon": -9.1440,
        }

    def test_a_namesake_far_away_is_not_it(self, auth_client, ai_on):
        trip_id, stop_id = _trip_with_stop(auth_client)
        r = auth_client.post(
            f"/api/trips/{trip_id}/plan/suggestions/locate",
            json={"stop_id": stop_id, "name": "Café Lisboa"},
        )
        assert r.status_code == 200 and r.json() is None

    def test_locating_does_not_count_against_the_daily_limit(self, auth_client, ai_on):
        trip_id, stop_id = _trip_with_stop(auth_client)
        auth_client.post(
            f"/api/trips/{trip_id}/plan/suggestions/locate",
            json={"stop_id": stop_id, "name": "Tasca do Chico"},
        )
        assert auth_client.get("/api/suggestions/status").json()["used_today"] == 0

    def test_another_users_trip_is_not_found(self, auth_client, api_app, ai_on):
        trip_id, stop_id = _trip_with_stop(auth_client)
        other = _make_user(api_app, "sugg_locate_other")
        r = other.post(
            f"/api/trips/{trip_id}/plan/suggestions/locate",
            json={"stop_id": stop_id, "name": "Tasca do Chico"},
        )
        assert r.status_code == 404


class TestSuggestMore:
    def test_suggesting_writes_nothing_to_the_plan(self, auth_client, ai_on):
        trip_id, stop_id = _trip_with_stop(auth_client)
        auth_client.post(f"/api/trips/{trip_id}/plan/suggestions", json={"stop_id": stop_id})
        assert auth_client.get(f"/api/trips/{trip_id}/plan").json()["items"] == []

    def test_a_day_resolves_to_the_city_slept_in(self, auth_client, ai_on):
        trip_id, _ = _trip_with_stop(auth_client)
        r = auth_client.post(f"/api/trips/{trip_id}/plan/suggestions", json={"date": "2027-05-12"})
        assert r.status_code == 200 and r.json()["day"] == "2027-05-12"
        sent = _sent(ai_on)
        assert sent["city"] == "Lisbon" and sent["for_day"] == "2027-05-12"

    def test_the_request_carries_interests_wish_language_and_the_plan(self, auth_client, ai_on):
        trip_id, stop_id = _trip_with_stop(auth_client)
        auth_client.patch("/api/auth/me", json={"locale": "pt-BR"})
        auth_client.post(f"/api/trips/{trip_id}/plan/items", json={"title": "Fado night"})
        auth_client.post(
            f"/api/trips/{trip_id}/plan/suggestions",
            json={
                "stop_id": stop_id,
                "interests": ["sights", "food", "nature"],
                "wish": "rainy day",
                "exclude": ["LX Factory"],
            },
        )
        sent = _sent(ai_on)
        assert sent["language"] == "Brazilian Portuguese"
        assert sent["interests"] == ["sights", "food", "nature"] and sent["wish"] == "rainy day"
        assert {"Fado night", "LX Factory"} <= set(sent["already_planned"])
        assert "past_trips" not in sent

    def test_an_unknown_interest_is_refused(self, auth_client, ai_on):
        trip_id, stop_id = _trip_with_stop(auth_client)
        r = auth_client.post(
            f"/api/trips/{trip_id}/plan/suggestions",
            json={"stop_id": stop_id, "interests": ["casinos"]},
        )
        assert r.status_code == 422

    def test_another_users_trip_is_not_found(self, auth_client, api_app, ai_on):
        trip_id, stop_id = _trip_with_stop(auth_client)
        other = _make_user(api_app, "sugg_other")
        r = other.post(f"/api/trips/{trip_id}/plan/suggestions", json={"stop_id": stop_id})
        assert r.status_code == 404
        ai_on.assert_not_called()

    def test_provider_trouble_is_a_503_not_a_crash(self, auth_client, ai_on):
        from backend.integrations.ai.client import AiUnreachableError

        ai_on.side_effect = AiUnreachableError("down")
        trip_id, stop_id = _trip_with_stop(auth_client)
        r = auth_client.post(f"/api/trips/{trip_id}/plan/suggestions", json={"stop_id": stop_id})
        assert r.status_code == 503 and r.json()["detail"] == "ai_unreachable"


class TestDailyLimit:
    def test_the_limit_is_per_user_per_day(self, auth_client, ai_on, monkeypatch):
        monkeypatch.setattr("backend.suggestions.service.settings.AI_SUGGESTIONS_DAILY_LIMIT", 2)
        trip_id, stop_id = _trip_with_stop(auth_client)
        url = f"/api/trips/{trip_id}/plan/suggestions"
        assert auth_client.post(url, json={"stop_id": stop_id}).status_code == 200
        assert auth_client.post(url, json={"stop_id": stop_id}).status_code == 200
        r = auth_client.post(url, json={"stop_id": stop_id})
        assert r.status_code == 429 and r.json()["detail"] == "daily_limit"
        assert ai_on.call_count == 2
        assert auth_client.get("/api/suggestions/status").json()["used_today"] == 2


class TestHistory:
    def _rated_trip(self, client, note):
        tid = client.post(
            "/api/trips",
            json={
                "name": "Porto",
                "planned_start_date": "2024-04-01",
                "planned_end_date": "2024-04-05",
            },
        ).json()["id"]
        client.put(f"/api/trips/{tid}/rating", json={"rating": 5})
        client.put(f"/api/trips/{tid}/note", json={"note": note})
        return tid

    def test_past_trips_are_sent_only_after_opting_in(self, auth_client, ai_on):
        self._rated_trip(auth_client, "Loved the tascas and the river walks")
        trip_id, stop_id = _trip_with_stop(auth_client)
        url = f"/api/trips/{trip_id}/plan/suggestions"

        auth_client.post(url, json={"stop_id": stop_id})
        assert "past_trips" not in _sent(ai_on)

        assert (
            auth_client.put("/api/suggestions/prefs", json={"use_history": True}).status_code == 200
        )
        assert auth_client.get("/api/suggestions/status").json()["use_history"] is True
        auth_client.post(url, json={"stop_id": stop_id})
        (past,) = _sent(ai_on)["past_trips"]
        assert past["stars"] == 5 and "tascas" in past["note"]


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


class TestNightsAndStay:
    def _stay(self, client, trip_id, lat=38.711, lon=-9.14):
        r = client.post(
            f"/api/trips/{trip_id}/stays",
            json={
                "kind": "hotel",
                "place": {"name": "Casa do Chiado", "lat": lat, "lon": lon},
                "check_in_datetime": "2027-05-10T15:00",
                "check_out_datetime": "2027-05-14T11:00",
            },
        )
        assert r.status_code in (200, 201), r.text

    def test_a_city_request_says_how_many_nights_and_where_they_sleep(self, auth_client, ai_on):
        trip_id, stop_id = _trip_with_stop(auth_client)
        self._stay(auth_client, trip_id)
        r = auth_client.post(f"/api/trips/{trip_id}/plan/suggestions", json={"stop_id": stop_id})
        sent = _sent(ai_on)
        assert sent["nights"] == 4 and sent["staying_at"] == "Casa do Chiado"
        assert r.json()["stay"] == {"name": "Casa do Chiado", "lat": 38.711, "lon": -9.14}
        assert r.json()["stay_without_pin"] is None

    def test_a_day_request_carries_no_nights(self, auth_client, ai_on):
        trip_id, _ = _trip_with_stop(auth_client)
        auth_client.post(f"/api/trips/{trip_id}/plan/suggestions", json={"date": "2027-05-12"})
        assert _sent(ai_on)["nights"] is None

    def test_a_stay_without_a_pin_is_named_not_guessed(self, auth_client, ai_on):
        trip_id, stop_id = _trip_with_stop(auth_client)
        r = auth_client.post(
            f"/api/trips/{trip_id}/stays",
            json={
                "kind": "hotel",
                "place": {"name": "Casa sem pino"},
                "check_in_datetime": "2027-05-10T15:00",
                "check_out_datetime": "2027-05-14T11:00",
            },
        )
        assert r.status_code in (200, 201), r.text
        body = auth_client.post(
            f"/api/trips/{trip_id}/plan/suggestions", json={"stop_id": stop_id}
        ).json()
        assert body["stay"] is None and body["stay_without_pin"] == "Casa sem pino"

    def test_no_booked_stay_means_no_distances(self, auth_client, ai_on):
        trip_id, stop_id = _trip_with_stop(auth_client)
        r = auth_client.post(f"/api/trips/{trip_id}/plan/suggestions", json={"stop_id": stop_id})
        assert r.json()["stay"] is None


class TestArrange:
    def _day(self, client):
        trip_id, _ = _trip_with_stop(client)
        ids = []
        for body in (
            {"title": "Dinner at Tasca", "date": "2027-05-12"},
            {"title": "Belém Tower", "date": "2027-05-12", "lat": 38.69, "lon": -9.21},
            {
                "title": "Fado show",
                "date": "2027-05-12",
                "time": "21:30",
                "status": "booked",
            },
        ):
            ids.append(client.post(f"/api/trips/{trip_id}/plan/items", json=body).json()["id"])
        return trip_id, ids

    def test_a_proposal_in_order_with_times_and_nothing_written(self, auth_client, ai_on):
        trip_id, (dinner, tower, fado) = self._day(auth_client)
        ai_on.return_value = {
            "plan": [
                {"ref": "2", "time": "09:30"},
                {"ref": "3", "time": "10:00"},  # a booked time is not the model's to move
                {"ref": "1", "time": "19:00"},
                {"ref": "9", "time": "12:00"},  # no such item
            ],
            "tip": "Book the fado.",
        }
        r = auth_client.post(
            f"/api/trips/{trip_id}/plan/arrange",
            json={
                "date": "2027-05-12",
                "busy": [{"start": "14:00", "end": "15:00", "label": "Train"}],
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert [(i["id"], i["time"]) for i in body["items"]] == [
            (tower, "09:30"),
            (dinner, "19:00"),
            (fado, "21:30"),
        ]
        assert body["items"][2]["fixed"] is True and body["tip"] == "Book the fado."
        sent = _sent(ai_on)
        assert sent["busy"] == [{"from": "14:00", "to": "15:00", "what": "Train"}]
        assert {i["ref"] for i in sent["items"]} == {"1", "2", "3"}
        items = auth_client.get(f"/api/trips/{trip_id}/plan").json()["items"]
        assert {i["time"] for i in items} == {None, "21:30"}

    def test_a_bad_time_or_a_forgotten_item_keeps_what_it_had(self, auth_client, ai_on):
        trip_id, (dinner, tower, fado) = self._day(auth_client)
        ai_on.return_value = {"plan": [{"ref": "2", "time": "9am"}], "tip": ""}
        body = auth_client.post(
            f"/api/trips/{trip_id}/plan/arrange", json={"date": "2027-05-12"}
        ).json()
        assert {i["id"]: i["time"] for i in body["items"]} == {
            tower: None,
            dinner: None,
            fado: "21:30",
        }
        assert body["tip"] is None

    def test_a_tip_that_is_not_text_is_dropped(self, auth_client, ai_on):
        trip_id, _ = self._day(auth_client)
        ai_on.return_value = {"plan": [], "tip": {"oops": 1}}
        body = auth_client.post(
            f"/api/trips/{trip_id}/plan/arrange", json={"date": "2027-05-12"}
        ).json()
        assert body["tip"] is None and len(body["items"]) == 3

    def test_shown_cards_survive_the_cap_on_what_is_sent(self, auth_client, ai_on):
        trip_id, stop_id = _trip_with_stop(auth_client)
        for n in range(80):
            auth_client.post(f"/api/trips/{trip_id}/plan/items", json={"title": f"Item {n}"})
        exclude = [f"Shown {n}" for n in range(50)]
        auth_client.post(
            f"/api/trips/{trip_id}/plan/suggestions",
            json={"stop_id": stop_id, "exclude": exclude},
        )
        assert set(exclude) <= set(_sent(ai_on)["already_planned"])

    def test_a_planned_title_beyond_the_cap_is_still_not_suggested(self, auth_client, ai_on):
        trip_id, stop_id = _trip_with_stop(auth_client)
        for n in range(80):
            auth_client.post(f"/api/trips/{trip_id}/plan/items", json={"title": f"Item {n}"})
        ai_on.return_value = {
            "suggestions": [
                {"name": "Item 79", "why": "x", "category": "sight", "best_time": "any"},
                {"name": "New place", "why": "y", "category": "sight", "best_time": "any"},
            ]
        }
        r = auth_client.post(
            f"/api/trips/{trip_id}/plan/suggestions",
            json={"stop_id": stop_id, "exclude": [f"Shown {n}" for n in range(50)]},
        )
        assert "Item 79" not in _sent(ai_on)["already_planned"]
        assert [c["title"] for c in r.json()["suggestions"]] == ["New place"]

    def test_one_item_is_nothing_to_arrange(self, auth_client, ai_on):
        trip_id, _ = _trip_with_stop(auth_client)
        auth_client.post(
            f"/api/trips/{trip_id}/plan/items", json={"title": "Only", "date": "2027-05-12"}
        )
        r = auth_client.post(f"/api/trips/{trip_id}/plan/arrange", json={"date": "2027-05-12"})
        assert r.status_code == 422 and r.json()["detail"] == "nothing_to_arrange"
        ai_on.assert_not_called()

    def test_another_users_trip_is_not_found(self, auth_client, api_app, ai_on):
        trip_id, _ = self._day(auth_client)
        other = _make_user(api_app, "arrange_other")
        r = other.post(f"/api/trips/{trip_id}/plan/arrange", json={"date": "2027-05-12"})
        assert r.status_code == 404
