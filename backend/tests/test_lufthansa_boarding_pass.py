"""Tests for the Lufthansa mobile boarding pass: enrichment, never a flight.

This format prints the flight number, route, date and *departure* time, and no
arrival time at all. It used to stand the departure in for the arrival, which
produced a zero-length leg that the plausibility gate discarded on every sync —
the flight was never stored either way, and the only trace was a log line that
read like a parse failure.

Measured against the 372-email corpus, all three emails in this format were for
legs already stored from their booking confirmations, with real arrival times.
So the boarding pass adds seat, gate, terminal and cabin to a leg the traveller
already has, which is what `_process_bcbp_email` has always done for BCBP
barcodes ("we don't have enough info to create a complete flight from BCBP
alone") — and a mobile boarding pass carries strictly less than a barcode does.
"""

import uuid
from datetime import UTC, datetime

import pytest

from backend.parsers.airlines.lufthansa import extract, extract_boarding_pass_details
from backend.parsers.builtin_rules import get_builtin_rules
from backend.parsers.shared import make_flight_dict


class _Email:
    def __init__(self, html_body="", body="", sender="boardingpass@lufthansa.com"):
        self.html_body = html_body
        self.body = body
        self.sender = sender
        self.subject = "You are checked-in: LH278, FRA-LIN, 24JAN19, 21:25, Gate A20"
        self.message_id = f"<{uuid.uuid4()}@example.com>"
        self.date = datetime(2019, 1, 24, 10, 0, tzinfo=UTC)


# Structure copied from a real mobile boarding pass, values invented. The
# value-then-label ordering ("19B\nSeat") is the layout's own and is what the
# extractor keys on.
BOARDING_PASS_HTML = """<html><body>
<div>Lufthansa Mobile Boarding Pass</div>
<div>Traveller, Sample</div><div>Passenger name</div>
<div>LH278</div><div>Flight</div>
<div>24JAN19</div><div>Date</div>
<div>FRA</div><div>Frankfurt</div>
<div>LIN</div><div>Milan</div>
<div>ECO LIGHT</div><div>Class</div>
<div>19B</div><div>Seat</div>
<div>A20</div><div>Gate</div>
<div>Terminal: 1</div>
<div>21:25</div><div>Boarding</div>
<div>TESTREF</div><div>Booking code</div>
<div>LH278</div><div>Voo</div>
<div>21:55</div><div>Partida</div>
</body></html>"""


class TestNoFlightIsInvented:
    def test_a_boarding_pass_yields_no_flights(self):
        """The whole point: this email describes no storable leg."""
        rule = next(r for r in get_builtin_rules() if r.airline_name == "Lufthansa")
        # Called directly rather than through `rule.extractor`, which is typed
        # `object`; that the rule is wired to it is asserted in TestOptInContract.
        assert extract(_Email(BOARDING_PASS_HTML), rule) == []

    def test_equal_local_times_are_still_a_valid_flight(self):
        """Regression guard, and the reason the fix lives in the parser rather
        than in `make_flight_dict`.

        Refusing a leg whose arrival equals its departure looks like an obvious
        guard at the choke point and silently dropped two real Finnair legs:
        AY813 leaves Helsinki at 14:00 and lands in Stockholm at 14:00, a real
        one-hour flight across a one-hour offset. These are naive local times;
        only `apply_airport_timezones` makes them comparable, so ordering is
        `validation.py`'s call. A parser with no arrival time must return
        nothing instead of standing the departure in for it.
        """
        rule = next(r for r in get_builtin_rules() if r.airline_name == "Lufthansa")
        when = datetime(2024, 7, 31, 14, 0)
        assert make_flight_dict(rule, "AY813", "HEL", "ARN", when, when) is not None

    def test_a_real_arrival_still_builds_a_flight(self):
        rule = next(r for r in get_builtin_rules() if r.airline_name == "Lufthansa")
        dep = datetime(2019, 1, 24, 21, 55)
        arr = datetime(2019, 1, 24, 23, 5)
        flight = make_flight_dict(rule, "LH278", "FRA", "LIN", dep, arr)
        assert flight is not None
        assert flight["flight_number"] == "LH278"


class TestDetailExtraction:
    def test_reads_every_field_the_pass_carries(self):
        (record,) = extract_boarding_pass_details(_Email(BOARDING_PASS_HTML))
        assert record["flight_number"] == "LH278"
        assert record["departure_date"] == "2019-01-24"
        assert record["departure_airport"] == "FRA"
        assert record["arrival_airport"] == "LIN"
        assert record["seat"] == "19B"
        assert record["gate"] == "A20"
        assert record["departure_terminal"] == "1"
        assert record["cabin_class"] == "ECO LIGHT"
        assert record["booking_reference"] == "TESTREF"
        assert record["passenger_name"] == "Traveller, Sample"

    def test_an_unassigned_gate_is_simply_absent(self):
        """Real passes are issued before the gate is known; the subject of one
        such email literally reads 'Gate ....'."""
        html = BOARDING_PASS_HTML.replace("<div>A20</div><div>Gate</div>", "")
        (record,) = extract_boarding_pass_details(_Email(html))
        assert "gate" not in record
        assert record["seat"] == "19B"

    def test_a_non_boarding_pass_email_yields_nothing(self):
        assert extract_boarding_pass_details(_Email("<html><body>Hello</body></html>")) == []

    def test_no_html_yields_nothing(self):
        assert extract_boarding_pass_details(_Email()) == []


class TestOptInContract:
    def test_lufthansa_exposes_the_extractor(self):
        rule = next(r for r in get_builtin_rules() if r.airline_name == "Lufthansa")
        assert callable(rule.boarding_pass_extractor)

    def test_airlines_without_one_are_not_an_error(self):
        others = [r for r in get_builtin_rules() if r.airline_name != "Lufthansa"]
        assert others, "expected other airline rules to exist"
        assert all(r.boarding_pass_extractor is None for r in others)


@pytest.mark.usefixtures("test_db")
class TestPipelineEnrichment:
    """The end the traveller sees: the seat lands on the flight they already have."""

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
               VALUES (?,1,'LH','Lufthansa','LH278','FRA','LIN',
                       '2019-01-24T20:55:00+00:00','2019-01-24T22:05:00+00:00',
                       'past',0,?,?)""",
            (fid, now, now),
        )
        conn.commit()
        return conn, fid

    def test_seat_and_gate_land_on_the_stored_flight(self, test_db):
        from backend.sync.pipeline import _process_emails

        conn, fid = self._setup(test_db)
        result = _process_emails([_Email(BOARDING_PASS_HTML)], 1)

        assert result["flights_created"] == 0, "a boarding pass must never create a flight"
        assert result["flights_updated"] >= 1
        row = conn.execute(
            "SELECT seat, departure_gate, departure_terminal, cabin_class, booking_reference "
            "FROM flights WHERE id = ?",
            (fid,),
        ).fetchone()
        assert row["seat"] == "19B"
        assert row["departure_gate"] == "A20"
        assert row["departure_terminal"] == "1"
        assert row["cabin_class"] == "ECO LIGHT"
        assert row["booking_reference"] == "TESTREF"
        conn.close()

    def test_an_existing_value_is_not_overwritten(self, test_db):
        """The booking confirmation is the authority, and a seat the traveller
        edited by hand must survive a pass reprinted after a gate change."""
        from backend.sync.pipeline import _process_emails

        conn, fid = self._setup(test_db)
        conn.execute("UPDATE flights SET seat = '1A' WHERE id = ?", (fid,))
        conn.commit()

        _process_emails([_Email(BOARDING_PASS_HTML)], 1)

        row = conn.execute(
            "SELECT seat, departure_gate FROM flights WHERE id = ?", (fid,)
        ).fetchone()
        assert row["seat"] == "1A", "the stored seat was overwritten"
        assert row["departure_gate"] == "A20", "an empty field should still be filled"
        conn.close()

    def test_a_pass_for_an_unknown_flight_changes_nothing(self, test_db):
        from backend.sync.pipeline import _process_emails

        conn, _ = self._setup(test_db)
        html = BOARDING_PASS_HTML.replace("LH278", "LH999")
        result = _process_emails([_Email(html)], 1)

        assert result["flights_created"] == 0
        assert conn.execute("SELECT COUNT(*) c FROM flights").fetchone()["c"] == 1
        conn.close()
