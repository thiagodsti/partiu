"""Tests for backend.sync.pipeline utility functions."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


def _make_email_msg(message_id="<test@example.com>", subject="Test", body="", html_body=""):
    from backend.parsers.email_connector import EmailMessage

    return EmailMessage(
        message_id=message_id,
        sender="airline@example.com",
        subject=subject,
        body=body,
        date=datetime.now(UTC),
        html_body=html_body,
        pdf_attachments=[],
    )


class TestDtToIso:
    def test_none_returns_none(self):
        from backend.utils import dt_to_iso

        assert dt_to_iso(None) is None

    def test_aware_datetime(self):
        from backend.utils import dt_to_iso

        dt = datetime(2025, 6, 1, 10, 0, 0, tzinfo=UTC)
        result = dt_to_iso(dt)
        assert "2025-06-01" in result
        assert "+" in result or "Z" in result or "UTC" in result

    def test_naive_datetime_gets_utc(self):
        from backend.utils import dt_to_iso

        dt = datetime(2025, 6, 1, 10, 0, 0)
        result = dt_to_iso(dt)
        assert "2025-06-01" in result


class TestIsNonFlightDomain:
    def test_empty_sender_returns_false(self, test_db):
        from backend.sync.pipeline import is_non_flight_domain

        assert is_non_flight_domain("") is False

    def test_matches_hardcoded_domain(self, test_db):
        from backend.sync.pipeline import is_non_flight_domain

        assert is_non_flight_domain("reservations@booking.com") is True

    def test_matches_hardcoded_subdomain(self, test_db):
        from backend.sync.pipeline import is_non_flight_domain

        assert is_non_flight_domain("noreply@property.booking.com") is True

    def test_unknown_domain_returns_false(self, test_db):
        from backend.sync.pipeline import is_non_flight_domain

        assert is_non_flight_domain("noreply@latam.com") is False

    def test_matches_admin_added_domain(self, test_db):
        from backend.settings.repository import SettingsRepository
        from backend.sync.pipeline import is_non_flight_domain

        SettingsRepository().add_non_flight_domain("example.com")

        assert is_non_flight_domain("noreply@example.com") is True
        assert is_non_flight_domain("noreply@mail.example.com") is True


class TestSyncState:
    """_get_sync_state/_upsert_sync_state now live as SyncRepository methods
    (see test_sync_repository.py) — these tests cover the thin pipeline
    wrappers _set_sync_status/_set_sync_complete built on top of them."""

    def test_set_and_get_sync_status(self, test_db):
        from backend.database import db_write
        from backend.sync.pipeline import _set_sync_status
        from backend.sync.repository import SyncRepository

        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES ('u1', 'h', 1)"
            )
            user_id = cur.lastrowid

        _set_sync_status(user_id, "syncing")
        state = SyncRepository().get_latest_state(user_id)
        assert state is not None
        assert state.status == "syncing"

    def test_set_sync_status_updates_existing(self, test_db):
        from backend.database import db_write
        from backend.sync.pipeline import _set_sync_status
        from backend.sync.repository import SyncRepository

        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES ('u2', 'h', 1)"
            )
            user_id = cur.lastrowid

        _set_sync_status(user_id, "syncing")
        _set_sync_status(user_id, "idle", error="")
        state = SyncRepository().get_latest_state(user_id)
        assert state is not None
        assert state.status == "idle"

    def test_set_sync_complete(self, test_db):
        from backend.database import db_write
        from backend.sync.pipeline import _set_sync_complete
        from backend.sync.repository import SyncRepository

        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES ('u3', 'h', 1)"
            )
            user_id = cur.lastrowid

        now_iso = datetime.now(UTC).isoformat()
        _set_sync_complete(user_id, now_iso)
        state = SyncRepository().get_latest_state(user_id)
        assert state is not None
        assert state.status == "idle"
        assert state.last_synced_at == now_iso

    def test_set_sync_complete_updates_existing(self, test_db):
        from backend.database import db_write
        from backend.sync.pipeline import _set_sync_complete, _set_sync_status
        from backend.sync.repository import SyncRepository

        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES ('u4', 'h', 1)"
            )
            user_id = cur.lastrowid

        _set_sync_status(user_id, "syncing")
        now_iso = datetime.now(UTC).isoformat()
        _set_sync_complete(user_id, now_iso)
        state = SyncRepository().get_latest_state(user_id)
        assert state is not None
        assert state.status == "idle"


class TestSyncedFlightFields:
    def test_builds_dedup_key_and_computed_fields(self, test_db):
        from backend.sync.pipeline import _synced_flight_fields

        email_msg = _make_email_msg(message_id="<unique-msg-id@test.com>")
        flight_data = {
            "flight_number": "LA8094",
            "departure_airport": "GRU",
            "departure_datetime": datetime(2025, 6, 1, 10, 0, 0, tzinfo=UTC),
            "arrival_airport": "LHR",
            "arrival_datetime": datetime(2025, 6, 1, 22, 0, 0, tzinfo=UTC),
        }

        fields = _synced_flight_fields(flight_data, email_msg)
        assert fields["email_message_id"] == "<unique-msg-id@test.com>:LA8094"
        assert fields["duration_minutes"] == 720


class TestInsertSyncedFlight:
    def test_insert_new_flight(self, test_db):
        from backend.database import db_conn, db_write
        from backend.sync.pipeline import _insert_synced_flight

        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES ('u', 'h', 1)"
            )
            user_id = cur.lastrowid

        email_msg = _make_email_msg(message_id="<unique-msg-id@test.com>")
        flight_data = {
            "flight_number": "LA8094",
            "departure_airport": "GRU",
            "departure_datetime": datetime(2025, 6, 1, 10, 0, 0, tzinfo=UTC),
            "arrival_airport": "LHR",
            "arrival_datetime": datetime(2025, 6, 1, 22, 0, 0, tzinfo=UTC),
        }

        flight_id = _insert_synced_flight(flight_data, email_msg, user_id)
        assert flight_id is not None

        with db_conn() as conn:
            row = conn.execute("SELECT * FROM flights WHERE id = ?", (flight_id,)).fetchone()
        assert row is not None
        assert row["flight_number"] == "LA8094"

    def test_duplicate_message_id_returns_none(self, test_db):
        from backend.database import db_write
        from backend.sync.pipeline import _insert_synced_flight

        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES ('u2', 'h', 1)"
            )
            user_id = cur.lastrowid

        email_msg = _make_email_msg(message_id="<dup-msg@test.com>")
        flight_data = {
            "flight_number": "LA1111",
            "departure_airport": "GRU",
            "departure_datetime": datetime(2025, 6, 1, 10, 0, 0, tzinfo=UTC),
            "arrival_airport": "LHR",
            "arrival_datetime": datetime(2025, 6, 1, 22, 0, 0, tzinfo=UTC),
        }

        fid1 = _insert_synced_flight(flight_data, email_msg, user_id)
        fid2 = _insert_synced_flight(flight_data, email_msg, user_id)
        assert fid1 is not None
        assert fid2 is None  # duplicate

    def test_status_completed_for_past_flight(self, test_db):
        from backend.database import db_conn, db_write
        from backend.sync.pipeline import _insert_synced_flight

        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES ('u3', 'h', 1)"
            )
            user_id = cur.lastrowid

        email_msg = _make_email_msg(message_id="<past-flight@test.com>")
        flight_data = {
            "flight_number": "LA2222",
            "departure_airport": "GRU",
            "departure_datetime": datetime(2020, 1, 1, 10, 0, 0, tzinfo=UTC),
            "arrival_airport": "LHR",
            "arrival_datetime": datetime(2020, 1, 1, 22, 0, 0, tzinfo=UTC),
        }

        fid = _insert_synced_flight(flight_data, email_msg, user_id)
        with db_conn() as conn:
            row = conn.execute("SELECT status FROM flights WHERE id = ?", (fid,)).fetchone()
        assert row["status"] == "completed"


class TestUpdateFlightFromBcbp:
    def test_updates_seat_and_cabin(self, test_db):
        import uuid

        from backend.database import db_conn, db_write
        from backend.sync.pipeline import _update_flight_from_bcbp

        now = datetime.now(UTC).isoformat()
        fid = str(uuid.uuid4())
        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES ('u', 'h', 1)"
            )
            user_id = cur.lastrowid
            conn.execute(
                "INSERT INTO flights (id, flight_number, departure_airport, departure_datetime, "
                "arrival_airport, arrival_datetime, user_id, created_at, updated_at) "
                "VALUES (?, 'LA1', 'GRU', '2025-06-01T10:00:00', 'LHR', '2025-06-01T22:00:00', ?, ?, ?)",
                (fid, user_id, now, now),
            )

        _update_flight_from_bcbp(fid, user_id, {"seat": "22A", "cabin_class": "economy"})

        with db_conn() as conn:
            row = conn.execute(
                "SELECT seat, cabin_class FROM flights WHERE id = ?", (fid,)
            ).fetchone()
        assert row["seat"] == "22A"
        assert row["cabin_class"] == "economy"

    def test_empty_bcbp_data_no_update(self, test_db):
        """If bcbp data has no relevant fields, no update is executed."""
        from backend.sync.pipeline import _update_flight_from_bcbp

        # Should not raise even with no updates
        _update_flight_from_bcbp("nonexistent-id", 1, {})


class TestProcessedEmails:
    """Raw is_email_processed/mark_email_processed CRUD now lives on SyncRepository
    (see test_sync_repository.py) — these tests cover _process_emails' use of it."""

    def _insert_user(self, conn, username="pe_user"):
        cur = conn.execute(
            f"INSERT INTO users (username, password_hash, is_admin) VALUES ('{username}', 'h', 1)"
        )
        return cur.lastrowid

    def test_process_emails_skips_processed_email(self, test_db):
        from backend.database import db_write
        from backend.sync.pipeline import _process_emails
        from backend.sync.repository import SyncRepository

        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES ('pe_user5', 'h', 1)"
            )
            user_id = cur.lastrowid

        msg_id = "<already-done@test.com>"
        SyncRepository().mark_email_processed(user_id, msg_id)

        email_msg = _make_email_msg(message_id=msg_id, subject="Flight confirmation")

        with patch("backend.sync.pipeline.match_rule_to_email") as mock_match:
            result = _process_emails([email_msg], user_id)
            mock_match.assert_not_called()

        assert result["flights_created"] == 0

    def test_process_emails_marks_email_after_flight_insert(self, test_db):
        from datetime import UTC, datetime

        from backend.database import db_write
        from backend.sync.pipeline import _process_emails
        from backend.sync.repository import SyncRepository

        with db_write() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES ('pe_user6', 'h', 1)"
            )
            user_id = cur.lastrowid

        msg_id = "<new-flight@test.com>"
        email_msg = _make_email_msg(message_id=msg_id)

        flight_data = {
            "flight_number": "LA9999",
            "departure_airport": "GRU",
            "departure_datetime": datetime(2025, 8, 1, 10, 0, tzinfo=UTC),
            "arrival_airport": "LHR",
            "arrival_datetime": datetime(2025, 8, 1, 22, 0, tzinfo=UTC),
        }

        with (
            patch("backend.sync.pipeline.match_rule_to_email", return_value=MagicMock()),
            patch("backend.sync.pipeline.extract_flights_from_email", return_value=[flight_data]),
            patch("backend.sync.pipeline.apply_airport_timezones", side_effect=lambda x: x),
            patch("backend.sync.pipeline.auto_group_flights", return_value={}),
            patch("backend.sync.pipeline._process_boarding_pass_email", return_value=0),
            patch("backend.sync.pipeline._process_bcbp_email", return_value=(0, 0)),
        ):
            result = _process_emails([email_msg], user_id)

        assert result["flights_created"] == 1
        assert SyncRepository().is_email_processed(user_id, msg_id) is True


class TestProcessBcbpEmail:
    def test_no_body_returns_zero(self, test_db):
        from backend.sync.pipeline import _process_bcbp_email

        email_msg = _make_email_msg(body="")
        legs, updated = _process_bcbp_email(email_msg, 1)
        assert legs == 0
        assert updated == 0

    def test_body_without_bcbp_returns_zero(self, test_db):
        from backend.sync.pipeline import _process_bcbp_email

        email_msg = _make_email_msg(body="Hello, your flight is confirmed.")
        legs, updated = _process_bcbp_email(email_msg, 1)
        assert legs == 0
        assert updated == 0


class TestApplyCancellations:
    """`_apply_cancellations` is the only path by which a cancellation email
    ever reaches a flight that is already stored. Every parser in the package
    refuses to *create* a cancelled leg; until this existed, nothing went back
    to the leg the booking confirmation had created weeks earlier."""

    @staticmethod
    def _user(username):
        from backend.database import db_write

        with db_write() as conn:
            return conn.execute(
                "INSERT INTO users (username, password_hash, is_admin) VALUES (?, 'h', 1)",
                (username,),
            ).lastrowid

    @staticmethod
    def _flight(user_id, *, number, ref, email_date, status="upcoming", manual=0):
        import uuid as _uuid

        from backend.database import db_write

        flight_id = str(_uuid.uuid4())
        with db_write() as conn:
            conn.execute(
                """INSERT INTO flights (
                       id, flight_number, booking_reference,
                       departure_airport, departure_datetime,
                       arrival_airport, arrival_datetime,
                       status, email_date, is_manually_added,
                       user_id, created_at, updated_at
                   ) VALUES (?, ?, ?, 'ARN', '2024-03-29T07:15:00+00:00',
                             'VIE', '2024-03-29T09:15:00+00:00', ?, ?, ?, ?, 'x', 'x')""",
                (flight_id, number, ref, status, email_date, manual, user_id),
            )
        return flight_id

    @staticmethod
    def _status(flight_id):
        from backend.database import db_conn

        with db_conn() as conn:
            return conn.execute("SELECT status FROM flights WHERE id = ?", (flight_id,)).fetchone()[
                "status"
            ]

    @staticmethod
    def _rule(records):
        rule = MagicMock()
        rule.cancellation_extractor = lambda email_msg: records
        return rule

    def test_a_booking_cancellation_marks_every_leg_under_that_reference(self, test_db):
        from backend.sync.pipeline import _apply_cancellations

        user_id = self._user("cancel_u1")
        out = self._flight(
            user_id, number="SK1", ref="QQ7RTX", email_date="2024-01-01T00:00:00+00:00"
        )
        back = self._flight(
            user_id, number="SK2", ref="QQ7RTX", email_date="2024-01-01T00:00:00+00:00"
        )
        other = self._flight(
            user_id, number="SK3", ref="OTHER1", email_date="2024-01-01T00:00:00+00:00"
        )

        email = _make_email_msg(subject="Cancellation Confirmation")
        n = _apply_cancellations(self._rule([{"booking_reference": "QQ7RTX"}]), email, user_id)

        assert n == 2
        assert self._status(out) == "cancelled"
        assert self._status(back) == "cancelled"
        assert self._status(other) == "upcoming"

    def test_a_leg_cancellation_leaves_its_siblings_alone(self, test_db):
        """Austrian cancels one flight out of a booking that holds the return
        too. Widening that to the booking would strike off a leg the traveller
        is still flying."""
        from backend.sync.pipeline import _apply_cancellations

        user_id = self._user("cancel_u2")
        outbound = self._flight(
            user_id, number="OS318", ref="SAMEREF", email_date="2024-01-01T00:00:00+00:00"
        )
        ret = self._flight(
            user_id, number="OS319", ref="SAMEREF", email_date="2024-01-01T00:00:00+00:00"
        )

        email = _make_email_msg(subject="Cancellation of your flight OS318")
        n = _apply_cancellations(
            self._rule([{"flight_number": "OS318", "departure_date": "2024-03-29"}]),
            email,
            user_id,
        )

        assert n == 1
        assert self._status(outbound) == "cancelled"
        assert self._status(ret) == "upcoming"

    def test_a_cancellation_older_than_the_flight_is_ignored(self, test_db):
        """An airline that cancels and rebooks often reissues under the same
        PNR, so a stored leg whose source email is *newer* than the cancellation
        describes the rebooking. Same "newer email wins" rule the pipeline
        already applies when a restated itinerary updates a stored flight."""
        from backend.sync.pipeline import _apply_cancellations

        user_id = self._user("cancel_u3")
        rebooked = self._flight(
            user_id, number="SK1", ref="QQ7RTX", email_date="2030-01-01T00:00:00+00:00"
        )

        email = _make_email_msg(subject="Cancellation Confirmation")
        n = _apply_cancellations(self._rule([{"booking_reference": "QQ7RTX"}]), email, user_id)

        assert n == 0
        assert self._status(rebooked) == "upcoming"

    def test_a_hand_typed_flight_is_still_cancellable(self, test_db):
        """A cancellation is a fact about the world, not about how the row
        reached the database. A manual flight has no source email to compare
        against, which must not exempt it."""
        from backend.sync.pipeline import _apply_cancellations

        user_id = self._user("cancel_u4")
        manual = self._flight(user_id, number="SK1", ref="QQ7RTX", email_date=None, manual=1)

        email = _make_email_msg(subject="Cancellation Confirmation")
        n = _apply_cancellations(self._rule([{"booking_reference": "QQ7RTX"}]), email, user_id)

        assert n == 1
        assert self._status(manual) == "cancelled"

    def test_re_reading_the_same_mail_changes_nothing(self, test_db):
        """A cancellation email is never marked processed (it creates no flight),
        so every incremental sync reads it again. The already-cancelled filter is
        what keeps that a no-op instead of a repeated write and a repeated push."""
        from backend.sync.pipeline import _apply_cancellations

        user_id = self._user("cancel_u5")
        self._flight(user_id, number="SK1", ref="QQ7RTX", email_date="2024-01-01T00:00:00+00:00")

        email = _make_email_msg(subject="Cancellation Confirmation")
        rule = self._rule([{"booking_reference": "QQ7RTX"}])
        assert _apply_cancellations(rule, email, user_id) == 1
        assert _apply_cancellations(rule, email, user_id) == 0

    def test_another_users_booking_is_untouched(self, test_db):
        from backend.sync.pipeline import _apply_cancellations

        mine = self._user("cancel_u6")
        theirs = self._user("cancel_u7")
        their_flight = self._flight(
            theirs, number="SK1", ref="QQ7RTX", email_date="2024-01-01T00:00:00+00:00"
        )

        email = _make_email_msg(subject="Cancellation Confirmation")
        n = _apply_cancellations(self._rule([{"booking_reference": "QQ7RTX"}]), email, mine)

        assert n == 0
        assert self._status(their_flight) == "upcoming"

    def test_an_airline_that_does_not_opt_in_is_skipped(self, test_db):
        from backend.sync.pipeline import _apply_cancellations

        rule = MagicMock()
        rule.cancellation_extractor = None
        assert _apply_cancellations(rule, _make_email_msg(), 1) == 0

    def test_a_failing_extractor_does_not_break_the_sync(self, test_db):
        from backend.sync.pipeline import _apply_cancellations

        rule = MagicMock()

        def _boom(email_msg):
            raise ValueError("bad mail")

        rule.cancellation_extractor = _boom
        assert _apply_cancellations(rule, _make_email_msg(), 1) == 0
