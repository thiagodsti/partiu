"""EmailReviewService: what qualifies for review, and what each action does."""

import sqlite3
from unittest.mock import patch

import pytest

from backend.email_review.service import CandidateNotFoundError, EmailReviewService

from .helpers import BODY, email, make_user, seed_airports


@pytest.fixture
def svc(test_db):
    seed_airports(test_db)
    return EmailReviewService()


def _rows(db, sql, *args):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _flight(db, user_id, number):
    conn = sqlite3.connect(db)
    conn.execute(
        """INSERT INTO flights (id, user_id, flight_number, departure_airport, departure_datetime,
               arrival_airport, arrival_datetime, created_at, updated_at)
           VALUES (?, ?, ?, 'FLN', '2018-11-16T17:40:00+00:00', 'GRU', '2018-11-16T19:00:00+00:00', 'x', 'x')""",
        (f"f-{number}", user_id, number),
    )
    conn.commit()
    conn.close()


class TestConsider:
    def test_a_missed_booking_is_offered_once(self, svc, test_db):
        user_id = make_user(test_db)
        msg = email()
        assert svc.consider(msg, user_id) is True
        assert svc.consider(msg, user_id) is False
        (item,) = svc.list_pending(user_id)
        assert item["hints"]["flight_numbers"] == ["O66175"]
        assert item["booking_reference"] == "PVNQDY"

    def test_marketing_is_not_offered(self, svc, test_db):
        user_id = make_user(test_db)
        assert svc.consider(email(subject="Ganhe milhas na sua próxima viagem"), user_id) is False

    def test_an_email_about_a_flight_already_stored_is_not_offered(self, svc, test_db):
        user_id = make_user(test_db)
        _flight(test_db, user_id, "O66175")
        assert svc.consider(email(), user_id) is False

    def test_no_airport_means_nothing_to_import(self, svc, test_db):
        user_id = make_user(test_db)
        body = "Código da reserva: X1Y2Z3\nVoo BG389 às 10:00 na agência"
        assert svc.consider(email(subject="Booking confirmation", body=body), user_id) is False

    def test_the_same_booking_restated_is_offered_once(self, svc, test_db):
        user_id = make_user(test_db)
        assert svc.consider(email(), user_id)
        assert svc.consider(email(subject="Recibo da sua passagem e-ticket"), user_id) is False

    def test_an_ignored_sender_is_not_offered(self, svc, test_db):
        user_id = make_user(test_db)
        svc.consider(email(), user_id)
        (item,) = svc.list_pending(user_id)
        svc.ignore_sender(user_id, item["id"])
        other = email(body=BODY.replace("O66175", "O61234").replace("PVNQDY", "ABC123"))
        assert svc.consider(other, user_id) is False


class TestActions:
    def _offer(self, svc, user_id):
        svc.consider(email(), user_id)
        return svc.list_pending(user_id)[0]["id"]

    def test_dismiss_closes_it_and_drops_the_text(self, svc, test_db):
        user_id = make_user(test_db)
        cid = self._offer(svc, user_id)
        svc.dismiss(user_id, cid)
        assert svc.count_pending(user_id) == 0
        (row,) = _rows(test_db, "SELECT status, body_text FROM email_candidates WHERE id = ?", cid)
        assert (row["status"], row["body_text"]) == ("dismissed", None)

    def test_another_user_s_email_is_not_found(self, svc, test_db):
        cid = self._offer(svc, make_user(test_db))
        with pytest.raises(CandidateNotFoundError):
            svc.dismiss(make_user(test_db), cid)

    def test_stop_ignoring_lets_the_sender_s_mail_be_offered_again(self, svc, test_db):
        user_id = make_user(test_db)
        cid = self._offer(svc, user_id)
        assert svc.ignore_sender(user_id, cid) == 1
        assert [s["domain"] for s in svc.list_ignored_senders(user_id)] == ["maxmilhas.example"]

        svc.stop_ignoring(user_id, "maxmilhas.example")
        assert svc.list_ignored_senders(user_id) == []
        # The dismissed copy is forgotten, so a full sync can offer it again.
        assert svc.consider(email(), user_id) is True

    def test_stop_ignoring_an_unknown_sender(self, svc, test_db):
        with pytest.raises(CandidateNotFoundError):
            svc.stop_ignoring(make_user(test_db), "nobody.example")

    def test_import_creates_the_flights_in_a_trip_and_closes_it(self, svc, test_db):
        user_id = make_user(test_db)
        cid = self._offer(svc, user_id)
        leg = {
            "flight_number": "O6 6175",
            "departure_airport": "fln",
            "arrival_airport": "GRU",
            "departure_datetime": "2018-11-16T15:40",
            "arrival_datetime": "2018-11-16T17:00",
            "booking_reference": "PVNQDY",
        }
        result = svc.import_legs(user_id, cid, [leg])
        (flight,) = _rows(test_db, "SELECT * FROM flights WHERE user_id = ?", user_id)
        assert (flight["flight_number"], flight["departure_airport"]) == ("O66175", "FLN")
        assert result["trip_ids"] == [flight["trip_id"]] and flight["trip_id"]
        assert svc.count_pending(user_id) == 0

    def test_a_bad_leg_saves_nothing(self, svc, test_db):
        user_id = make_user(test_db)
        cid = self._offer(svc, user_id)
        good = {
            "flight_number": "O66175",
            "departure_airport": "FLN",
            "arrival_airport": "GRU",
            "departure_datetime": "2018-11-16T15:40",
            "arrival_datetime": "2018-11-16T17:00",
        }
        bad = {**good, "arrival_airport": ""}
        with pytest.raises(ValueError, match="Flight 2"):
            svc.import_legs(user_id, cid, [good, bad])
        assert _rows(test_db, "SELECT id FROM flights WHERE user_id = ?", user_id) == []
        assert svc.count_pending(user_id) == 1

    def test_draft_needs_an_llm(self, svc, test_db):
        user_id = make_user(test_db)
        cid = self._offer(svc, user_id)
        with patch("backend.integrations.llm.parser.llm_available", return_value=False):
            with pytest.raises(LookupError):
                svc.draft(user_id, cid)

    def test_draft_hands_back_the_model_s_legs_with_the_email_s_date(self, svc, test_db):
        user_id = make_user(test_db)
        cid = self._offer(svc, user_id)
        drafted = [{"flight_number": "O66175", "doubts": {}}]
        with (
            patch("backend.integrations.llm.parser.llm_available", return_value=True),
            patch("backend.integrations.llm.parser.llm_draft_flights", return_value=drafted) as llm,
        ):
            assert svc.draft(user_id, cid) == drafted
        (msg,) = llm.call_args.args
        assert msg.date is not None and msg.date.year == 2018
