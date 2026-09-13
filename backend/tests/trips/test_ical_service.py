"""Tests for the iCalendar export: flights, ground segments and day-planner days.

Assertions run against the *unfolded* output, because RFC 5545 line folding
splits long values across continuation lines — a naive substring check on the
raw text would miss anything past 75 octets.
"""

import json
import uuid

import pytest

from backend.tests.segments.conftest import seed_trip, seed_user, segment_payload


def unfold(ics: str) -> str:
    """Undo RFC 5545 folding: CRLF followed by a single space or tab."""
    return ics.replace("\r\n ", "").replace("\r\n\t", "")


def events(ics: str) -> list[list[str]]:
    """Split the unfolded calendar into VEVENT blocks (alarms stay nested)."""
    lines = unfold(ics).split("\r\n")
    blocks: list[list[str]] = []
    current: list[str] | None = None
    depth = 0
    for line in lines:
        if line == "BEGIN:VEVENT":
            current, depth = [], 1
            continue
        if current is None:
            continue
        if line == "END:VEVENT":
            depth -= 1
            if depth == 0:
                blocks.append(current)
                current = None
                continue
        current.append(line)
    return blocks


def find_event(ics: str, needle: str) -> list[str] | None:
    for block in events(ics):
        if any(needle in line for line in block):
            return block
    return None


def value_of(block: list[str], prop: str) -> str | None:
    for line in block:
        if line.startswith(f"{prop}:") or line.startswith(f"{prop};"):
            return line.split(":", 1)[1]
    return None


def seed_day_note(db_path: str, trip_id: str, day: str, content: str, user_id: int) -> None:
    from backend.database import db_write
    from backend.utils import now_iso

    with db_write() as conn:
        conn.execute(
            """INSERT INTO trip_day_notes (trip_id, date, content, updated_at, updated_by)
               VALUES (?, ?, ?, ?, ?)""",
            (trip_id, day, content, now_iso(), user_id),
        )


def seed_flight(db_path: str, trip_id: str, user_id: int, **overrides) -> None:
    from backend.database import db_write
    from backend.utils import now_iso

    fields = {
        "flight_number": "LH722",
        "departure_airport": "FRA",
        "departure_datetime": "2026-10-01T11:40:00+00:00",
        "arrival_airport": "PEK",
        "arrival_datetime": "2026-10-01T22:20:00+00:00",
        "booking_reference": None,
        "passenger_name": None,
        "seat": None,
        "cabin_class": None,
        "aircraft_type": None,
    }
    fields.update(overrides)
    with db_write() as conn:
        conn.execute(
            f"""INSERT INTO flights (id, trip_id, user_id, created_at, updated_at,
                    {", ".join(fields)})
                VALUES (?, ?, ?, ?, ?, {", ".join("?" * len(fields))})""",
            (str(uuid.uuid4()), trip_id, user_id, now_iso(), now_iso(), *fields.values()),
        )


@pytest.fixture
def trip_ctx(test_db):
    user_id = seed_user(test_db)
    trip_id = seed_trip(test_db, user_id)
    return test_db, trip_id, user_id


def export(trip_id: str, user_id: int) -> str:
    from backend.trips.ical_service import IcalService

    content, _ = IcalService().export_ical(trip_id, user_id)
    return content


class TestSegments:
    def test_a_ground_leg_becomes_a_timed_event(self, trip_ctx):
        from backend.segments.service import SegmentService

        db_path, trip_id, user_id = trip_ctx
        SegmentService().create_segment(trip_id, user_id, segment_payload())

        block = find_event(export(trip_id, user_id), "China Railway G87")
        assert block is not None
        # 08:00 Beijing, floating: the wall clock the ticket prints, not the
        # 00:00Z instant behind it, which a calendar would rebase on the
        # reader's own zone.
        assert value_of(block, "DTSTART") == "20261004T080000"
        assert value_of(block, "DTEND") == "20261004T123000"
        assert "Beijing West Railway Station" in (value_of(block, "SUMMARY") or "")
        assert "Type: Train" in (value_of(block, "DESCRIPTION") or "")
        assert "Seat: Car 3\\, 12A" in (value_of(block, "DESCRIPTION") or "")

    def test_ground_leg_gets_a_reminder_like_a_flight(self, trip_ctx):
        from backend.segments.service import SegmentService

        db_path, trip_id, user_id = trip_ctx
        SegmentService().create_segment(trip_id, user_id, segment_payload())

        block = find_event(export(trip_id, user_id), "China Railway G87")
        assert block is not None
        assert "BEGIN:VALARM" in block
        assert "TRIGGER:-PT1H" in block

    def test_falls_back_to_the_type_when_unlabelled(self, trip_ctx):
        from backend.segments.service import SegmentService

        db_path, trip_id, user_id = trip_ctx
        SegmentService().create_segment(
            trip_id, user_id, segment_payload(type="ferry", operator=None, number=None)
        )

        block = find_event(export(trip_id, user_id), "Ferry:")
        assert block is not None

    def test_span_covers_a_segment_beyond_the_last_flight(self, trip_ctx):
        from backend.segments.service import SegmentService

        db_path, trip_id, user_id = trip_ctx
        seed_flight(db_path, trip_id, user_id)  # 1 Oct
        SegmentService().create_segment(trip_id, user_id, segment_payload())  # 4 Oct

        block = find_event(export(trip_id, user_id), "-span@partiu")
        assert block is not None
        assert (value_of(block, "DTEND") or "").startswith("20261004")


class TestDayNotes:
    def test_a_planner_day_becomes_an_all_day_event(self, trip_ctx):
        db_path, trip_id, user_id = trip_ctx
        seed_day_note(
            db_path,
            trip_id,
            "2026-10-05",
            json.dumps({"note": "Terracotta Army", "items": []}),
            user_id,
        )

        block = find_event(export(trip_id, user_id), "Terracotta Army")
        assert block is not None
        assert "DTSTART;VALUE=DATE:20261005" in block
        # DTEND on an all-day event is exclusive: the next day, or the event is
        # zero-length and vanishes in most clients.
        assert "DTEND;VALUE=DATE:20261006" in block

    def test_checklist_items_reach_the_description(self, trip_ctx):
        db_path, trip_id, user_id = trip_ctx
        seed_day_note(
            db_path,
            trip_id,
            "2026-10-05",
            json.dumps(
                {
                    "note": "Museum day",
                    "items": [
                        {"text": "Buy tickets", "checked": True},
                        {"text": "Pack water", "checked": False},
                    ],
                }
            ),
            user_id,
        )

        block = find_event(export(trip_id, user_id), "Museum day")
        assert block is not None
        description = value_of(block, "DESCRIPTION") or ""
        assert "☑ Buy tickets" in description
        assert "☐ Pack water" in description

    def test_summary_falls_back_to_the_first_checklist_item(self, trip_ctx):
        db_path, trip_id, user_id = trip_ctx
        seed_day_note(
            db_path,
            trip_id,
            "2026-10-05",
            json.dumps({"note": "", "items": [{"text": "Buy tickets", "checked": False}]}),
            user_id,
        )

        block = find_event(export(trip_id, user_id), "Buy tickets")
        assert block is not None
        assert value_of(block, "SUMMARY") == "Buy tickets"

    def test_summary_is_the_first_line_of_a_multiline_note(self, trip_ctx):
        db_path, trip_id, user_id = trip_ctx
        seed_day_note(
            db_path,
            trip_id,
            "2026-10-05",
            json.dumps({"note": "Great Wall\nLeave at dawn", "items": []}),
            user_id,
        )

        block = find_event(export(trip_id, user_id), "Great Wall")
        assert block is not None
        assert value_of(block, "SUMMARY") == "Great Wall"
        assert "Leave at dawn" in (value_of(block, "DESCRIPTION") or "")

    def test_long_summary_is_truncated_but_the_body_is_not(self, trip_ctx):
        db_path, trip_id, user_id = trip_ctx
        long_note = "x" * 200
        seed_day_note(
            db_path, trip_id, "2026-10-05", json.dumps({"note": long_note, "items": []}), user_id
        )

        block = find_event(export(trip_id, user_id), "xxx")
        assert block is not None
        summary = value_of(block, "SUMMARY") or ""
        assert len(summary) <= 61 and summary.endswith("…")
        assert long_note in (value_of(block, "DESCRIPTION") or "")

    def test_empty_days_produce_no_event(self, trip_ctx):
        db_path, trip_id, user_id = trip_ctx
        seed_day_note(
            db_path, trip_id, "2026-10-05", json.dumps({"note": "   ", "items": []}), user_id
        )
        seed_day_note(db_path, trip_id, "2026-10-06", "", user_id)

        assert events(export(trip_id, user_id)) == []

    def test_legacy_plain_text_content_still_exports(self, trip_ctx):
        db_path, trip_id, user_id = trip_ctx
        seed_day_note(db_path, trip_id, "2026-10-05", "Just some text", user_id)

        assert find_event(export(trip_id, user_id), "Just some text") is not None

    def test_legacy_block_array_content_still_exports(self, trip_ctx):
        db_path, trip_id, user_id = trip_ctx
        seed_day_note(
            db_path,
            trip_id,
            "2026-10-05",
            json.dumps(
                [
                    {"type": "text", "value": "Old format"},
                    {"type": "checklist", "items": [{"text": "Old item", "checked": False}]},
                ]
            ),
            user_id,
        )

        block = find_event(export(trip_id, user_id), "Old format")
        assert block is not None
        assert "☐ Old item" in (value_of(block, "DESCRIPTION") or "")


class TestEscapingAndFolding:
    def test_commas_and_semicolons_are_escaped(self, trip_ctx):
        """Unescaped, they split a TEXT field into a value list — a note reading
        "Beijing, then Xi'an" would corrupt the event."""
        db_path, trip_id, user_id = trip_ctx
        seed_day_note(
            db_path,
            trip_id,
            "2026-10-05",
            json.dumps({"note": "Beijing, then Xi'an; by train", "items": []}),
            user_id,
        )

        ics = export(trip_id, user_id)
        assert "Beijing\\, then Xi'an\\; by train" in unfold(ics)

    def test_newlines_become_literal_backslash_n(self, trip_ctx):
        db_path, trip_id, user_id = trip_ctx
        seed_day_note(
            db_path, trip_id, "2026-10-05", json.dumps({"note": "one\ntwo", "items": []}), user_id
        )

        block = find_event(export(trip_id, user_id), "one")
        assert block is not None
        assert value_of(block, "DESCRIPTION") == "one\\ntwo"

    def test_backslashes_are_escaped_once(self, trip_ctx):
        db_path, trip_id, user_id = trip_ctx
        seed_day_note(
            db_path, trip_id, "2026-10-05", json.dumps({"note": r"a\b", "items": []}), user_id
        )

        block = find_event(export(trip_id, user_id), "a")
        assert block is not None
        assert value_of(block, "SUMMARY") == "a\\\\b"

    def test_long_lines_are_folded_to_75_octets(self, trip_ctx):
        db_path, trip_id, user_id = trip_ctx
        seed_day_note(
            db_path, trip_id, "2026-10-05", json.dumps({"note": "y" * 500, "items": []}), user_id
        )

        ics = export(trip_id, user_id)
        assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))
        # …and unfolds back to the original content.
        assert "y" * 500 in unfold(ics)

    def test_folding_does_not_split_multibyte_characters(self, trip_ctx):
        """Folding counts octets; cutting mid-character would emit mojibake."""
        db_path, trip_id, user_id = trip_ctx
        seed_day_note(
            db_path,
            trip_id,
            "2026-10-05",
            json.dumps({"note": "北京西" * 60, "items": []}),
            user_id,
        )

        ics = export(trip_id, user_id)
        assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))
        assert "北京西" * 60 in unfold(ics)


class TestFlightsUnchanged:
    def test_flight_events_still_export(self, trip_ctx):
        db_path, trip_id, user_id = trip_ctx
        seed_flight(db_path, trip_id, user_id, booking_reference="XYZ123", seat="12A")

        block = find_event(export(trip_id, user_id), "LH722")
        assert block is not None
        assert value_of(block, "DTSTART") == "20261001T114000Z"
        assert "FRA → PEK" in (value_of(block, "SUMMARY") or "")
        assert "Booking Ref: XYZ123" in (value_of(block, "DESCRIPTION") or "")
        assert "BEGIN:VALARM" in block

    def test_everything_lands_in_one_calendar(self, trip_ctx):
        from backend.segments.service import SegmentService

        db_path, trip_id, user_id = trip_ctx
        seed_flight(db_path, trip_id, user_id)
        SegmentService().create_segment(trip_id, user_id, segment_payload())
        seed_day_note(
            db_path,
            trip_id,
            "2026-10-05",
            json.dumps({"note": "Terracotta Army", "items": []}),
            user_id,
        )

        ics = export(trip_id, user_id)
        # span + flight + segment + day note
        assert len(events(ics)) == 4
        assert ics.startswith("BEGIN:VCALENDAR")
        assert ics.endswith("END:VCALENDAR\r\n")


class TestTimezones:
    """Timed events carry the local wall clock at their own place.

    The point of the export: an itinerary should read the way its tickets do —
    the outbound at the origin's clock, the flight home at the destination's —
    rather than every time rebased on whatever zone the phone is in.
    """

    def test_each_end_of_a_flight_uses_its_own_airport(self, trip_ctx):
        db_path, trip_id, user_id = trip_ctx
        seed_flight(
            db_path,
            trip_id,
            user_id,
            departure_airport="LIS",
            departure_datetime="2026-10-01T13:00:00+00:00",
            departure_timezone="Europe/Lisbon",
            arrival_airport="GRU",
            arrival_datetime="2026-10-01T23:30:00+00:00",
            arrival_timezone="America/Sao_Paulo",
        )

        block = find_event(export(trip_id, user_id), "LIS → GRU")
        assert block is not None
        # 13:00Z is 14:00 in Lisbon (WEST); 23:30Z is 20:30 in São Paulo.
        assert value_of(block, "DTSTART") == "20261001T140000"
        assert value_of(block, "DTEND") == "20261001T203000"

    def test_a_flight_with_no_known_zone_stays_in_utc(self, trip_ctx):
        """Better a converted time than a wrong one presented as local."""
        db_path, trip_id, user_id = trip_ctx
        seed_flight(db_path, trip_id, user_id, departure_timezone=None, arrival_timezone=None)

        block = find_event(export(trip_id, user_id), "LH722")
        assert block is not None
        assert value_of(block, "DTSTART") == "20261001T114000Z"
        assert value_of(block, "DTEND") == "20261001T222000Z"

    def test_an_unknown_zone_name_falls_back_rather_than_raising(self, trip_ctx):
        # A zone this host has never heard of, e.g. a stale tzdata name.
        db_path, trip_id, user_id = trip_ctx
        seed_flight(db_path, trip_id, user_id, departure_timezone="Mars/Olympus_Mons")

        block = find_event(export(trip_id, user_id), "LH722")
        assert block is not None
        assert value_of(block, "DTSTART") == "20261001T114000Z"

    def test_floating_values_carry_no_zone_marker(self, trip_ctx):
        """A trailing Z or a TZID would both make the client convert again."""
        db_path, trip_id, user_id = trip_ctx
        seed_flight(db_path, trip_id, user_id, departure_timezone="Europe/Berlin")

        block = find_event(export(trip_id, user_id), "LH722")
        assert block is not None
        start = next(line for line in block if line.startswith("DTSTART"))
        assert start == "DTSTART:20261001T134000"
