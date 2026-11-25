"""Black-box tests of /api/email-review."""

from unittest.mock import patch

from backend.email_review.service import email_review_service

from .helpers import email, seed_airports


def _offer(test_db, auth_client):
    seed_airports(test_db)
    me = auth_client.get("/api/auth/me").json()
    email_review_service.consider(email(), me["id"])
    return auth_client.get("/api/email-review").json()["items"][0]["id"]


class TestEmailReviewApi:
    def test_list_and_count(self, test_db, auth_client):
        _offer(test_db, auth_client)
        body = auth_client.get("/api/email-review").json()
        assert len(body["items"]) == 1 and body["items"][0]["hints"]["airports"] == ["FLN", "GRU"]
        assert "ai_available" in body
        assert auth_client.get("/api/email-review/count").json() == {"count": 1}

    def test_dismiss(self, test_db, auth_client):
        cid = _offer(test_db, auth_client)
        assert auth_client.post(f"/api/email-review/{cid}/dismiss").status_code == 204
        assert auth_client.get("/api/email-review/count").json() == {"count": 0}

    def test_unknown_email_is_404(self, test_db, auth_client):
        assert auth_client.post("/api/email-review/nope/dismiss").status_code == 404

    def test_ignore_list_and_stop_ignoring(self, test_db, auth_client):
        cid = _offer(test_db, auth_client)
        assert auth_client.post(f"/api/email-review/{cid}/ignore-sender").json() == {"dismissed": 1}
        domains = [s["domain"] for s in auth_client.get("/api/email-review/ignored-senders").json()]
        assert domains == ["maxmilhas.example"]
        r = auth_client.delete("/api/email-review/ignored-senders/maxmilhas.example")
        assert r.status_code == 204
        assert auth_client.get("/api/email-review/ignored-senders").json() == []
        assert (
            auth_client.delete("/api/email-review/ignored-senders/maxmilhas.example").status_code
            == 404
        )

    def test_import_validates_before_saving(self, test_db, auth_client):
        cid = _offer(test_db, auth_client)
        leg = {
            "flight_number": "not a flight",
            "departure_airport": "FLN",
            "arrival_airport": "GRU",
            "departure_datetime": "2018-11-16T15:40",
            "arrival_datetime": "2018-11-16T17:00",
        }
        r = auth_client.post(f"/api/email-review/{cid}/import", json={"legs": [leg]})
        assert r.status_code == 422

    def test_draft_without_an_llm_is_409(self, test_db, auth_client):
        cid = _offer(test_db, auth_client)
        with patch("backend.integrations.llm.parser.llm_available", return_value=False):
            assert auth_client.post(f"/api/email-review/{cid}/draft").status_code == 409

    def test_draft_with_the_llm_down_is_503_with_a_code(self, test_db, auth_client):
        from backend.integrations.llm.parser import LlmUnreachableError

        cid = _offer(test_db, auth_client)
        with (
            patch("backend.integrations.llm.parser.llm_available", return_value=True),
            patch(
                "backend.integrations.llm.parser.llm_draft_flights",
                side_effect=LlmUnreachableError("x"),
            ),
        ):
            r = auth_client.post(f"/api/email-review/{cid}/draft")
        assert r.status_code == 503
        assert r.json()["detail"]["error"] == "ai_unreachable"
