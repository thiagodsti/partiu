"""
Test: LATAM boarding-pass mails enrich the leg they belong to.

Fixtures: tests/fixtures/latam_boarding_pass_milan_anonymized.json
            LA8072 on 16 Mar 2026, seat 14L, booking code MJGZWO
          tests/fixtures/latam_boarding_pass_sp_anonymized.json
            LA3357 on 16 Mar 2026, seat 18F, booking code GCUIWO

Ten of the thirty LATAM mails in the measured corpus are this template or its
predecessors, and until now none of them did anything: the pass carries no
arrival time, so `extract()` (correctly) builds no flight from it, and LATAM
exported no `extract_boarding_pass_details` for the pipeline to enrich with.
"""

import uuid
from datetime import UTC, datetime

import pytest
from conftest import load_anonymized_fixture

from backend.parsers.airlines.latam import extract, extract_boarding_pass_details


@pytest.fixture(scope="module")
def milan_pass():
    return load_anonymized_fixture("latam_boarding_pass_milan_anonymized.json")


@pytest.fixture(scope="module")
def sao_paulo_pass():
    return load_anonymized_fixture("latam_boarding_pass_sp_anonymized.json")


class TestDetailExtraction:
    def test_reads_flight_date_seat_reference_and_name(self, milan_pass):
        assert extract_boarding_pass_details(milan_pass) == [
            {
                "flight_number": "LA8072",
                "departure_date": "2026-03-16",
                "seat": "14L",
                "booking_reference": "MJGZWO",
                "passenger_name": "Batman da Silva",
            }
        ]

    def test_second_fixture(self, sao_paulo_pass):
        (record,) = extract_boarding_pass_details(sao_paulo_pass)
        assert (record["flight_number"], record["seat"], record["booking_reference"]) == (
            "LA3357",
            "18F",
            "GCUIWO",
        )

    def test_a_pass_never_creates_a_flight(self, milan_pass, seeded_airports_db):
        rule = type("Rule", (), {"airline_name": "LATAM Airlines", "airline_code": "LA"})()
        assert extract(milan_pass, rule) == []

    def test_a_non_pass_latam_mail_yields_nothing(self):
        from backend.parsers.email_connector import EmailMessage

        msg = EmailMessage(
            message_id="x",
            sender="info@info.latam.com",
            subject="Confira os horários do seu voo",
            body="",
            date=datetime(2026, 3, 15, tzinfo=UTC),
            html_body="<p>Voo LA8072</p><p>segunda-feira, 16 de março de 2026</p><p>18:00</p>",
        )
        assert extract_boarding_pass_details(msg) == []

    def test_the_rule_binds_the_hook(self):
        from backend.parsers.builtin_rules import get_builtin_rules

        rule = next(r for r in get_builtin_rules() if r.airline_code == "LA")
        assert rule.boarding_pass_extractor is extract_boarding_pass_details


@pytest.mark.usefixtures("test_db")
class TestPipelineEnrichment:
    @staticmethod
    def _setup(test_db):
        import backend.database as db_module

        conn = db_module.get_connection(test_db)
        now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO users (id, username, password_hash, is_admin, created_at) "
            "VALUES (1,'traveller','x',0,?)",
            (now,),
        )
        fid = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO flights (id, user_id, airline_code, airline_name, flight_number,
                 departure_airport, arrival_airport, departure_datetime, arrival_datetime,
                 status, is_manually_added, created_at, updated_at)
               VALUES (?,1,'LA','LATAM Airlines','LA8072','GRU','MXP',
                       '2026-03-16T21:00:00+00:00','2026-03-17T08:35:00+00:00',
                       'upcoming',0,?,?)""",
            (fid, now, now),
        )
        conn.commit()
        return conn, fid

    def test_seat_lands_on_the_stored_flight(self, test_db, milan_pass):
        from backend.sync.pipeline import _process_emails

        conn, fid = self._setup(test_db)
        result = _process_emails([milan_pass], 1)
        assert result["flights_created"] == 0
        assert result["flights_updated"] >= 1
        row = conn.execute(
            "SELECT seat, booking_reference, passenger_name FROM flights WHERE id = ?", (fid,)
        ).fetchone()
        assert (row["seat"], row["booking_reference"], row["passenger_name"]) == (
            "14L",
            "MJGZWO",
            "Batman da Silva",
        )
        conn.close()

    def test_a_hand_edited_seat_is_kept(self, test_db, milan_pass):
        from backend.sync.pipeline import _process_emails

        conn, fid = self._setup(test_db)
        conn.execute("UPDATE flights SET seat = '1A' WHERE id = ?", (fid,))
        conn.commit()
        _process_emails([milan_pass], 1)
        assert (
            conn.execute("SELECT seat FROM flights WHERE id = ?", (fid,)).fetchone()["seat"] == "1A"
        )
        conn.close()
