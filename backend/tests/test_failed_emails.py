"""Tests for failed emails API, parser keyword filter, and builtin_rules refactor."""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_and_login(client):
    r = client.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
    assert r.status_code == 200
    return client


def _insert_failed_email(test_db, user_id: int, subject="Booking Confirmed", reason="no rule matched"):
    from backend.database import db_write
    from backend.utils import now_iso

    eid = str(uuid.uuid4())
    with db_write() as conn:
        conn.execute(
            """INSERT INTO failed_emails
               (id, user_id, sender, subject, reason, parser_version, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (eid, user_id, "info@airline.com", subject, reason, "17", now_iso()),
        )
    return eid


# ---------------------------------------------------------------------------
# Tests: failed emails API
# ---------------------------------------------------------------------------


class TestFailedEmailsApi:
    def test_list_empty(self, auth_client):
        r = auth_client.get("/api/failed-emails")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_shows_own_emails(self, auth_client, test_db):
        from backend.database import db_conn

        with db_conn() as conn:
            user_id = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]

        _insert_failed_email(test_db, user_id)
        r = auth_client.get("/api/failed-emails")
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_delete_own_failed_email(self, auth_client, test_db):
        from backend.database import db_conn

        with db_conn() as conn:
            user_id = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]

        eid = _insert_failed_email(test_db, user_id)
        r = auth_client.delete(f"/api/failed-emails/{eid}")
        assert r.status_code == 204

        r = auth_client.get("/api/failed-emails")
        assert r.json() == []

    def test_delete_nonexistent_returns_404(self, auth_client):
        r = auth_client.delete("/api/failed-emails/nonexistent-id")
        assert r.status_code == 404

    def test_retry_no_eml_file_still_fails_gracefully(self, auth_client, test_db):
        """Retry when no EML file exists — should update last_retried_at and return still_failing."""
        from backend.database import db_conn

        with db_conn() as conn:
            user_id = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]

        eid = _insert_failed_email(test_db, user_id)
        r = auth_client.post(f"/api/failed-emails/{eid}/retry")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "still_failing"

    def test_retry_nonexistent_returns_404(self, auth_client):
        r = auth_client.post("/api/failed-emails/nonexistent-id/retry")
        assert r.status_code == 404

    def test_admin_list_grouped(self, auth_client, test_db):
        from backend.database import db_conn, db_write
        from backend.utils import now_iso

        with db_conn() as conn:
            user_id = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]

        # Insert two for same domain, one for different
        for _ in range(2):
            eid = str(uuid.uuid4())
            with db_write() as conn:
                conn.execute(
                    """INSERT INTO failed_emails
                       (id, user_id, sender, subject, reason, airline_hint, parser_version, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (eid, user_id, "info@tap.com", "Booking", "no rule", "tap.com", "17", now_iso()),
                )

        r = auth_client.get("/api/admin/failed-emails")
        assert r.status_code == 200
        groups = r.json()
        assert any(g["sender_domain"] == "tap.com" and g["count"] == 2 for g in groups)

    def test_admin_delete_sender(self, auth_client, test_db):
        from backend.database import db_conn, db_write
        from backend.utils import now_iso

        with db_conn() as conn:
            user_id = conn.execute("SELECT id FROM users LIMIT 1").fetchone()["id"]

        eid = str(uuid.uuid4())
        with db_write() as conn:
            conn.execute(
                """INSERT INTO failed_emails
                   (id, user_id, sender, subject, reason, airline_hint, parser_version, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (eid, user_id, "info@tap.com", "Booking", "no rule", "tap.com", "17", now_iso()),
            )

        r = auth_client.request(
            "DELETE",
            "/api/admin/failed-emails/sender",
            json={"sender": "tap.com"},
        )
        assert r.status_code == 204

        r = auth_client.get("/api/failed-emails")
        assert all(e["airline_hint"] != "tap.com" for e in r.json())


# ---------------------------------------------------------------------------
# Tests: parser builtin_rules refactor
# ---------------------------------------------------------------------------


class TestBuiltinRulesRefactor:
    def test_parser_version_constant_exists(self):
        from backend.parsers.builtin_rules import PARSER_VERSION

        assert PARSER_VERSION, "PARSER_VERSION must be set"
        assert isinstance(PARSER_VERSION, str)

    def test_rules_have_callable_extractor(self):
        from backend.parsers.builtin_rules import get_builtin_rules

        rules = get_builtin_rules()
        assert len(rules) > 0
        for rule in rules:
            assert callable(rule.extractor), (
                f"Rule '{rule.airline_name}' has no callable extractor"
            )

    def test_latam_extractor_callable(self):
        from backend.parsers.builtin_rules import get_builtin_rules

        latam = next(r for r in get_builtin_rules() if r.airline_code == "LA")
        assert callable(latam.extractor)

    def test_sas_extractor_callable(self):
        from backend.parsers.builtin_rules import get_builtin_rules

        sas = next(r for r in get_builtin_rules() if r.airline_code == "SK")
        assert callable(sas.extractor)

    def test_kiwi_extractor_callable(self):
        from backend.parsers.builtin_rules import get_builtin_rules

        kiwi = next(r for r in get_builtin_rules() if r.airline_name == "Kiwi.com")
        assert callable(kiwi.extractor)


# ---------------------------------------------------------------------------
# Tests: engine uses rule.extractor
# ---------------------------------------------------------------------------


class TestEngineCallableExtractor:
    def _make_rule_with_extractor(self, extractor_fn=None):
        from backend.parsers.builtin_rules import BuiltinAirlineRule

        rule = BuiltinAirlineRule(
            airline_name="TestAir",
            airline_code="TA",
            sender_pattern=r"testair\.com",
            body_pattern="",
            date_format="%d %b %Y",
            time_format="%H:%M",
            is_active=True,
            is_builtin=True,
            priority=10,
            custom_extractor="",
            extractor=extractor_fn,
        )
        return rule

    def _make_email(self):
        from backend.parsers.email_connector import EmailMessage

        return EmailMessage(
            message_id="test-001",
            sender="info@testair.com",
            subject="Booking Confirmed",
            body="Test body",
            date=datetime.now(UTC),
            html_body="<html><body>Test</body></html>",
        )

    def test_engine_calls_rule_extractor(self):
        """engine.py should call rule.extractor when it is not None."""
        from backend.parsers.engine import extract_flights_from_email

        called = []

        def fake_extractor(email_msg, rule):
            called.append(True)
            return []

        rule = self._make_rule_with_extractor(fake_extractor)
        email_msg = self._make_email()
        extract_flights_from_email(email_msg, rule)
        assert called, "rule.extractor should have been called"

    def test_engine_returns_extractor_results(self):
        """When rule.extractor returns flights, they should be returned by the engine."""
        from backend.parsers.engine import extract_flights_from_email

        fake_flight = {
            "airline_name": "TestAir",
            "airline_code": "TA",
            "flight_number": "TA123",
            "departure_airport": "GRU",
            "arrival_airport": "LHR",
            "departure_datetime": datetime.now(UTC),
            "arrival_datetime": datetime.now(UTC),
            "booking_reference": "",
            "passenger_name": "",
            "seat": "",
            "cabin_class": "",
            "departure_terminal": "",
            "arrival_terminal": "",
            "departure_gate": "",
            "arrival_gate": "",
        }

        rule = self._make_rule_with_extractor(lambda e, r: [fake_flight])
        email_msg = self._make_email()
        results = extract_flights_from_email(email_msg, rule)
        assert len(results) == 1
        assert results[0]["flight_number"] == "TA123"

    def test_engine_falls_back_when_extractor_raises(self):
        """When rule.extractor raises, engine should fall back to generic regex."""
        from backend.parsers.engine import extract_flights_from_email

        def failing_extractor(email_msg, rule):
            raise RuntimeError("extractor failed")

        rule = self._make_rule_with_extractor(failing_extractor)
        email_msg = self._make_email()
        # Should not raise; just return empty (no body_pattern set)
        results = extract_flights_from_email(email_msg, rule)
        assert results == []


# ---------------------------------------------------------------------------
# Tests: _matches_flight_filter in email_connector
# ---------------------------------------------------------------------------


class TestFlightKeywordFilter:
    def test_known_sender_pattern_matches(self):
        from backend.parsers.email_connector import _matches_flight_filter

        assert _matches_flight_filter(
            "noreply@latam.com",
            "Anything",
            [r"latam\.com"],
        )

    def test_flight_keyword_in_subject_matches(self):
        from backend.parsers.email_connector import _matches_flight_filter

        assert _matches_flight_filter(
            "info@unknownairline.com",
            "Your e-ticket for LA8094",
            [r"latam\.com"],
        )

    def test_booking_confirm_keyword_matches(self):
        from backend.parsers.email_connector import _matches_flight_filter

        assert _matches_flight_filter(
            "noreply@tap.com",
            "Booking confirmation for your trip",
            None,
        )

    def test_random_email_does_not_match(self):
        from backend.parsers.email_connector import _matches_flight_filter

        assert not _matches_flight_filter(
            "newsletter@shop.com",
            "Your order has been shipped",
            [r"latam\.com"],
        )

    def test_no_patterns_no_keyword_does_not_match(self):
        from backend.parsers.email_connector import _matches_flight_filter

        assert not _matches_flight_filter(
            "random@example.com",
            "Hello World",
            None,
        )


# ---------------------------------------------------------------------------
# Tests: _merge_flights in engine
# ---------------------------------------------------------------------------


class TestMergeFlights:
    def _flight(self, fn, dep, arr, seat="", booking=""):
        return {
            "flight_number": fn,
            "departure_airport": dep,
            "arrival_airport": arr,
            "seat": seat,
            "booking_reference": booking,
            "departure_datetime": datetime.now(UTC),
            "arrival_datetime": datetime.now(UTC),
        }

    def test_primary_empty_returns_secondary(self):
        from backend.parsers.engine import _merge_flights

        sec = [self._flight("LA123", "GRU", "LHR", seat="12A")]
        assert _merge_flights([], sec) == sec

    def test_secondary_empty_returns_primary(self):
        from backend.parsers.engine import _merge_flights

        pri = [self._flight("LA123", "GRU", "LHR")]
        assert _merge_flights(pri, []) == pri

    def test_fills_empty_seat_from_secondary(self):
        from backend.parsers.engine import _merge_flights

        pri = [self._flight("LA123", "GRU", "LHR", seat="")]
        sec = [self._flight("LA123", "GRU", "LHR", seat="14C")]
        result = _merge_flights(pri, sec)
        assert result[0]["seat"] == "14C"

    def test_does_not_overwrite_existing_field(self):
        from backend.parsers.engine import _merge_flights

        pri = [self._flight("LA123", "GRU", "LHR", seat="12A", booking="ABC123")]
        sec = [self._flight("LA123", "GRU", "LHR", seat="14C", booking="DIFFERENT")]
        result = _merge_flights(pri, sec)
        assert result[0]["seat"] == "12A"
        assert result[0]["booking_reference"] == "ABC123"

    def test_secondary_only_flight_appended(self):
        from backend.parsers.engine import _merge_flights

        pri = [self._flight("LA123", "GRU", "LHR")]
        sec = [self._flight("LA999", "GRU", "CDG")]
        result = _merge_flights(pri, sec)
        assert len(result) == 2
        assert any(f["flight_number"] == "LA999" for f in result)


# ---------------------------------------------------------------------------
# Tests: save_failed_email dedup
# ---------------------------------------------------------------------------


class TestSaveFailedEmail:
    def test_same_email_not_saved_twice(self, test_db):
        from backend.database import db_conn
        from backend.failed_email_queue import save_failed_email
        from backend.parsers.email_connector import EmailMessage

        msg = EmailMessage(
            message_id="dup-001",
            sender="info@tap.com",
            subject="Booking Confirmation",
            body="test",
            date=datetime.now(UTC),
        )

        save_failed_email(1, msg, "no rule matched")
        save_failed_email(1, msg, "no rule matched")  # duplicate

        with db_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM failed_emails WHERE sender = ?", ("info@tap.com",)
            ).fetchone()[0]

        assert count == 1, "Duplicate failed email should not be inserted twice"

    def test_eml_saved_to_disk(self, test_db, tmp_path, monkeypatch):
        import backend.config as cfg_mod

        monkeypatch.setattr(cfg_mod.settings, "DB_PATH", str(tmp_path / "test.db"))

        from backend.failed_email_queue import save_failed_email
        from backend.parsers.email_connector import EmailMessage

        raw = b"From: info@tap.com\r\nSubject: Test\r\n\r\nBody"
        msg = EmailMessage(
            message_id="raw-001",
            sender="info@tap.com",
            subject="Test Subject",
            body="Body",
            date=datetime.now(UTC),
            raw_eml=raw,
        )

        save_failed_email(1, msg, "no rule matched")

        eml_dir = tmp_path / "failed_emails"
        eml_files = list(eml_dir.glob("*.eml"))
        assert len(eml_files) == 1
        assert eml_files[0].read_bytes() == raw
