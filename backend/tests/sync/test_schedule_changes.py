"""
Test: schedule changes reach the flights the traveller already has.

Three shapes of change mail, three behaviours:

* An itinerary reprinted with new times (TAP "Reservation Change", Lufthansa's
  "alteração de reserva") already overwrote the stored leg through the
  "newer email wins" rule — silently. Now the previous times are kept on the
  row, the row is stamped, and the traveller is told.
* A leg moved to another *day* used to miss the number-plus-date lookup and be
  created beside the old one. `find_moved_leg` joins it on number, route and
  booking reference within a few days instead.
* A notice that names the booking and prints no itinerary (SAS) can update
  nothing; its legs are flagged with the notice date and the traveller pointed
  at the airline.

The change mails here are GDS compact receipts written with bare IATA codes,
which parse with no airline rule and no airports table — the point under test
is the pipeline's bookkeeping, not any one parser.
"""

import uuid
from datetime import UTC, datetime

import pytest
from conftest import load_anonymized_fixture

from backend.parsers.email_connector import EmailMessage


def _receipt(
    *, date: datetime, ref: str, legs: list[str], message_id: str | None = None
) -> EmailMessage:
    body = "ELECTRONIC TICKET RECEIPT\nBOOKING REF: " + ref + "\n" + "\n".join(legs) + "\n"
    return EmailMessage(
        message_id=message_id or f"<{uuid.uuid4()}@example.com>",
        sender="tickets@example.com",
        subject="Electronic ticket receipt",
        body=body,
        date=date,
    )


def _user(test_db):
    import backend.database as db_module

    conn = db_module.get_connection(test_db)
    conn.execute(
        "INSERT INTO users (id, username, password_hash, is_admin, created_at) VALUES (1,'t','x',0,?)",
        (datetime.now(UTC).isoformat(),),
    )
    # No coordinates on purpose: with none, local times pass through as UTC and
    # the expected instants below read exactly as the receipts print them.
    conn.executemany(
        "INSERT OR IGNORE INTO airports (iata_code, name, city_name, country_code) VALUES (?,?,?,?)",
        [
            ("ARN", "Stockholm Arlanda", "Stockholm", "SE"),
            ("LIS", "Lisbon", "Lisbon", "PT"),
            ("CPH", "Copenhagen", "Copenhagen", "DK"),
        ],
    )
    conn.commit()
    from backend.parsers.shared import is_valid_iata, resolve_iata

    is_valid_iata.cache_clear()
    resolve_iata.cache_clear()
    from backend.notifications import push_service

    push_service.update_preferences(1, {"delay_alert": True})
    return conn


def _flights(conn, ref):
    return conn.execute(
        "SELECT * FROM flights WHERE booking_reference = ? ORDER BY departure_datetime", (ref,)
    ).fetchall()


def _notifications(conn, kind):
    return conn.execute("SELECT title, body FROM notifications WHERE type = ?", (kind,)).fetchall()


ISSUE = datetime(2027, 8, 1, 10, 0, tzinfo=UTC)
CHANGE = datetime(2027, 9, 1, 10, 0, tzinfo=UTC)


@pytest.mark.usefixtures("test_db")
class TestTimesMovedOnTheSameDay:
    def test_previous_times_are_kept_and_the_traveller_told(self, test_db):
        from backend.sync.pipeline import _process_emails

        conn = _user(test_db)
        _process_emails(
            [_receipt(date=ISSUE, ref="RESCH1", legs=["TP 783 / 10NOV ARN - LIS 19:05 22:35"])], 1
        )
        (before,) = _flights(conn, "RESCH1")
        assert before["rescheduled_at"] is None

        result = _process_emails(
            [_receipt(date=CHANGE, ref="RESCH1", legs=["TP 783 / 10NOV ARN - LIS 19:30 23:00"])], 1
        )
        assert result["flights_created"] == 0
        assert result["flights_rescheduled"] == 1
        (after,) = _flights(conn, "RESCH1")
        assert after["id"] == before["id"]
        assert after["departure_datetime"] == "2027-11-10T19:30:00+00:00"
        assert after["rescheduled_from_departure"] == "2027-11-10T19:05:00+00:00"
        assert after["rescheduled_from_arrival"] == "2027-11-10T22:35:00+00:00"
        assert after["rescheduled_at"] == CHANGE.isoformat()
        (note,) = _notifications(conn, "rescheduled")
        assert "TP783" in note["title"]
        assert "19:30" in note["body"] and "19:05" in note["body"]
        conn.close()

    def test_an_identical_reprint_is_not_a_reschedule(self, test_db):
        from backend.sync.pipeline import _process_emails

        conn = _user(test_db)
        leg = ["TP 783 / 10NOV ARN - LIS 19:05 22:35"]
        _process_emails([_receipt(date=ISSUE, ref="RESCH2", legs=leg)], 1)
        result = _process_emails([_receipt(date=CHANGE, ref="RESCH2", legs=leg)], 1)
        assert result["flights_rescheduled"] == 0
        (row,) = _flights(conn, "RESCH2")
        assert row["rescheduled_at"] is None
        assert _notifications(conn, "rescheduled") == []
        conn.close()

    def test_an_older_mail_never_moves_a_flight(self, test_db):
        from backend.sync.pipeline import _process_emails

        conn = _user(test_db)
        _process_emails(
            [_receipt(date=CHANGE, ref="RESCH3", legs=["TP 783 / 10NOV ARN - LIS 19:30 23:00"])], 1
        )
        result = _process_emails(
            [_receipt(date=ISSUE, ref="RESCH3", legs=["TP 783 / 10NOV ARN - LIS 19:05 22:35"])], 1
        )
        assert (result["flights_created"], result["flights_rescheduled"]) == (0, 0)
        (row,) = _flights(conn, "RESCH3")
        assert row["departure_datetime"] == "2027-11-10T19:30:00+00:00"
        conn.close()

    def test_a_rescan_of_the_same_change_notifies_once(self, test_db):
        from backend.sync.pipeline import _process_emails

        conn = _user(test_db)
        _process_emails(
            [_receipt(date=ISSUE, ref="RESCH4", legs=["TP 783 / 10NOV ARN - LIS 19:05 22:35"])], 1
        )
        change = _receipt(date=CHANGE, ref="RESCH4", legs=["TP 783 / 10NOV ARN - LIS 19:30 23:00"])
        _process_emails([change], 1)
        _process_emails([change], 1, skip_dedup=True)
        assert len(_notifications(conn, "rescheduled")) == 1
        conn.close()


@pytest.mark.usefixtures("test_db")
class TestLegMovedToAnotherDay:
    def test_the_same_row_is_moved_not_duplicated(self, test_db):
        from backend.sync.pipeline import _process_emails

        conn = _user(test_db)
        _process_emails(
            [_receipt(date=ISSUE, ref="MOVED1", legs=["TP 783 / 10NOV ARN - LIS 19:05 22:35"])], 1
        )
        (before,) = _flights(conn, "MOVED1")
        result = _process_emails(
            [_receipt(date=CHANGE, ref="MOVED1", legs=["TP 783 / 11NOV ARN - LIS 07:00 10:30"])], 1
        )
        assert result["flights_created"] == 0
        rows = _flights(conn, "MOVED1")
        assert len(rows) == 1
        assert rows[0]["id"] == before["id"]
        assert rows[0]["departure_datetime"] == "2027-11-11T07:00:00+00:00"
        assert rows[0]["rescheduled_from_departure"] == "2027-11-10T19:05:00+00:00"
        conn.close()

    def test_a_different_route_is_a_different_leg(self, test_db):
        from backend.sync.pipeline import _process_emails

        conn = _user(test_db)
        _process_emails(
            [_receipt(date=ISSUE, ref="MOVED2", legs=["TP 783 / 10NOV ARN - LIS 19:05 22:35"])], 1
        )
        _process_emails(
            [_receipt(date=CHANGE, ref="MOVED2", legs=["TP 783 / 11NOV LIS - ARN 07:00 10:30"])], 1
        )
        assert len(_flights(conn, "MOVED2")) == 2
        conn.close()

    def test_a_different_booking_is_a_different_leg(self, test_db):
        from backend.sync.pipeline import _process_emails

        conn = _user(test_db)
        _process_emails(
            [_receipt(date=ISSUE, ref="MOVED3", legs=["TP 783 / 10NOV ARN - LIS 19:05 22:35"])], 1
        )
        _process_emails(
            [_receipt(date=CHANGE, ref="OTHER3", legs=["TP 783 / 11NOV ARN - LIS 19:05 22:35"])], 1
        )
        assert len(_flights(conn, "MOVED3")) == 1 and len(_flights(conn, "OTHER3")) == 1
        conn.close()

    def test_too_far_apart_is_a_second_booking_of_the_same_flight(self, test_db):
        from backend.sync.pipeline import _process_emails

        conn = _user(test_db)
        _process_emails(
            [_receipt(date=ISSUE, ref="MOVED4", legs=["TP 783 / 10NOV ARN - LIS 19:05 22:35"])], 1
        )
        _process_emails(
            [_receipt(date=CHANGE, ref="MOVED4", legs=["TP 783 / 20NOV ARN - LIS 19:05 22:35"])], 1
        )
        assert len(_flights(conn, "MOVED4")) == 2
        conn.close()


class TestSasNoticeParser:
    def test_names_the_booking(self):
        from backend.parsers.airlines.sas import extract_schedule_changes

        email = load_anonymized_fixture("sas_schedule_change_anonymized.json")
        assert extract_schedule_changes(email) == [{"booking_reference": "TESTRF"}]

    def test_is_not_a_cancellation(self):
        # Same mail, same reference, and the words "Cancel your booking" as an
        # option — test_cancellations.py pins this too; here it guards the pair.
        from backend.parsers.airlines.sas import extract_cancellations

        assert (
            extract_cancellations(load_anonymized_fixture("sas_schedule_change_anonymized.json"))
            == []
        )

    def test_a_confirmation_is_not_a_notice(self):
        from backend.parsers.airlines.sas import extract_schedule_changes

        email = EmailMessage(
            message_id="x",
            sender="no-reply@flysas.com",
            subject="Your SAS booking TESTRF",
            body="Thank you for booking. Booking reference: TESTRF",
            date=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert extract_schedule_changes(email) == []

    def test_the_rule_binds_the_hook(self):
        from backend.parsers.airlines.sas import extract_schedule_changes
        from backend.parsers.builtin_rules import get_builtin_rules

        rule = next(r for r in get_builtin_rules() if r.airline_code == "SK")
        assert rule.schedule_change_extractor is extract_schedule_changes


@pytest.mark.usefixtures("test_db")
class TestNoticeWithoutItinerary:
    NOTICE = "sas_schedule_change_anonymized.json"

    def test_flags_every_leg_of_the_booking_and_notifies(self, test_db):
        from backend.sync.pipeline import _process_emails

        conn = _user(test_db)
        _process_emails(
            [
                _receipt(
                    date=datetime(2024, 6, 1, tzinfo=UTC),
                    ref="TESTRF",
                    legs=[
                        "SK 1401 / 10DEC ARN - CPH 08:00 09:10",
                        "SK 1402 / 14DEC CPH - ARN 18:00 19:10",
                    ],
                )
            ],
            1,
        )
        result = _process_emails([load_anonymized_fixture(self.NOTICE)], 1)
        assert result["flights_rescheduled"] == 2
        rows = _flights(conn, "TESTRF")
        assert {r["schedule_change_notice_at"] for r in rows} == {"2024-12-07T07:21:34+00:00"}
        assert len(_notifications(conn, "schedule_change")) == 2
        conn.close()

    def test_a_rescan_is_a_no_op(self, test_db):
        from backend.sync.pipeline import _process_emails

        conn = _user(test_db)
        _process_emails(
            [
                _receipt(
                    date=datetime(2024, 6, 1, tzinfo=UTC),
                    ref="TESTRF",
                    legs=["SK 1401 / 10DEC ARN - CPH 08:00 09:10"],
                )
            ],
            1,
        )
        notice = load_anonymized_fixture(self.NOTICE)
        first = _process_emails([notice], 1)
        second = _process_emails([notice], 1, skip_dedup=True)
        assert (first["flights_rescheduled"], second["flights_rescheduled"]) == (1, 0)
        assert len(_notifications(conn, "schedule_change")) == 1
        conn.close()

    def test_a_leg_already_reissued_after_the_notice_is_left_alone(self, test_db):
        from backend.sync.pipeline import _process_emails

        conn = _user(test_db)
        _process_emails(
            [
                _receipt(
                    date=datetime(2024, 12, 20, tzinfo=UTC),
                    ref="TESTRF",
                    legs=["SK 1401 / 10JAN ARN - CPH 08:00 09:10"],
                )
            ],
            1,
        )
        result = _process_emails([load_anonymized_fixture(self.NOTICE)], 1)
        assert result["flights_rescheduled"] == 0
        (row,) = _flights(conn, "TESTRF")
        assert row["schedule_change_notice_at"] is None
        conn.close()

    def test_a_newer_itinerary_clears_the_notice(self, test_db):
        from backend.sync.pipeline import _process_emails

        conn = _user(test_db)
        _process_emails(
            [
                _receipt(
                    date=datetime(2024, 6, 1, tzinfo=UTC),
                    ref="TESTRF",
                    legs=["SK 1401 / 10DEC ARN - CPH 08:00 09:10"],
                )
            ],
            1,
        )
        _process_emails([load_anonymized_fixture(self.NOTICE)], 1)
        _process_emails(
            [
                _receipt(
                    date=datetime(2024, 12, 8, tzinfo=UTC),
                    ref="TESTRF",
                    legs=["SK 1401 / 10DEC ARN - CPH 09:30 10:40"],
                )
            ],
            1,
        )
        (row,) = _flights(conn, "TESTRF")
        assert row["schedule_change_notice_at"] is None
        assert row["rescheduled_from_departure"] == "2024-12-10T08:00:00+00:00"
        conn.close()


class TestTapReservationChangeParses:
    """The TAP change mail reprints the itinerary, so it needs no hook at all —
    it must simply parse, and then the pipeline's update does the rest."""

    def test_reads_the_new_times(self, seeded_airports_db):
        from backend.parsers.builtin_rules import get_builtin_rules
        from backend.parsers.engine import extract_flights_from_email, match_rule_to_email

        email = load_anonymized_fixture("tap_reservation_change_anonymized.json")
        rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
        rule = match_rule_to_email(email, rules)
        assert rule is not None and rule.airline_code == "TP"
        flights = extract_flights_from_email(email, rule)
        assert [
            (f["flight_number"], f["departure_datetime"].strftime("%H:%M")) for f in flights
        ] == [
            ("TP783", "19:30"),
            ("TP780", "08:05"),
        ]
