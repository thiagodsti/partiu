"""Tests for the stay half of the trip iCalendar export."""

from backend.tests.stays.conftest import HOTEL_LISBON, seed_trip, seed_user, stay_payload


def _export(test_db, user_id: int, trip_id: str) -> str:
    from backend.trips.ical_service import IcalService

    content, _ = IcalService().export_ical(trip_id, user_id)
    return content


def _events(ics: str) -> list[list[str]]:
    """Split an .ics into its VEVENT bodies, unfolding continuation lines."""
    unfolded = ics.replace("\r\n ", "")
    events, current = [], None
    for line in unfolded.split("\r\n"):
        if line == "BEGIN:VEVENT":
            current = []
        elif line == "END:VEVENT" and current is not None:
            events.append(current)
            current = None
        elif current is not None:
            current.append(line)
    return events


def _find(events, prefix: str):
    return [e for e in events if any(line.startswith(prefix) for line in e)]


def _value(event: list[str], key: str) -> str | None:
    """The value of `key` in this event, or None when the property is absent."""
    for line in event:
        if line.startswith(key):
            return line.split(":", 1)[1]
    return None


def _require(event: list[str], key: str) -> str:
    """Same, but fails the test outright when the property is missing — so an
    assertion about its content cannot pass vacuously against a None."""
    value = _value(event, key)
    assert value is not None, f"{key} missing from event"
    return value


def _setup(test_db, **overrides):
    from backend.stays.service import StayService

    user_id = seed_user(test_db)
    trip_id = seed_trip(test_db, user_id)
    StayService().create_stay(trip_id, user_id, stay_payload(**overrides))
    return user_id, trip_id


class TestStayBlock:
    def test_all_day_block_covers_the_checkout_morning(self, test_db):
        """DTEND is exclusive on an all-day event. A 4-8 October booking must
        end on the 9th, or the block stops on the 7th and the morning the guest
        is still there falls outside it."""
        user_id, trip_id = _setup(test_db)
        block = _find(_events(_export(test_db, user_id, trip_id)), "DTSTART;VALUE=DATE:20261004")
        assert len(block) == 1
        assert _require(block[0], "DTSTART;VALUE=DATE") == "20261004"
        assert _require(block[0], "DTEND;VALUE=DATE") == "20261009"

    def test_summary_is_the_property_name(self, test_db):
        user_id, trip_id = _setup(test_db)
        block = _find(_events(_export(test_db, user_id, trip_id)), "DTSTART;VALUE=DATE:20261004")[0]
        assert _require(block, "SUMMARY") == "Hotel Avenida Palace"

    def test_location_prefers_the_street_address(self, test_db):
        """The address is what makes the entry tappable through to a maps app."""
        user_id, trip_id = _setup(test_db)
        block = _find(_events(_export(test_db, user_id, trip_id)), "DTSTART;VALUE=DATE:20261004")[0]
        location = _require(block, "LOCATION")
        assert "1º de Dezembro" in location
        # The comma in the address is escaped, or it would split LOCATION into
        # a value list.
        assert "\\," in location

    def test_location_falls_back_to_the_name_without_an_address(self, test_db):
        user_id, trip_id = _setup(test_db, kind="airbnb", place={"name": "Flat in Alfama"})
        block = _find(_events(_export(test_db, user_id, trip_id)), "DTSTART;VALUE=DATE:20261004")[0]
        assert _require(block, "LOCATION") == "Flat in Alfama"

    def test_geo_is_emitted_only_with_coordinates(self, test_db):
        user_id, trip_id = _setup(test_db)
        block = _find(_events(_export(test_db, user_id, trip_id)), "DTSTART;VALUE=DATE:20261004")[0]
        assert _require(block, "GEO") == f"{HOTEL_LISBON['lat']};{HOTEL_LISBON['lon']}"

    def test_no_geo_for_a_hand_typed_place(self, test_db):
        """A missing GEO is right; (0, 0) would pin the stay off West Africa."""
        user_id, trip_id = _setup(test_db, kind="airbnb", place={"name": "Flat in Alfama"})
        block = _find(_events(_export(test_db, user_id, trip_id)), "DTSTART;VALUE=DATE:20261004")[0]
        assert _value(block, "GEO") is None

    def test_description_carries_the_booking_details(self, test_db):
        user_id, trip_id = _setup(test_db, confirmation="CONF-9", room_type="Double")
        block = _find(_events(_export(test_db, user_id, trip_id)), "DTSTART;VALUE=DATE:20261004")[0]
        description = _require(block, "DESCRIPTION")
        assert "Nights: 4" in description
        assert "Booking Ref: BK12345" in description
        assert "Confirmation: CONF-9" in description
        assert "Room: Double" in description


class TestCheckoutReminder:
    def test_a_separate_timed_event_carries_the_alarm(self, test_db):
        """An alarm on an all-day event fires at midnight in whatever zone the
        client picks, so the reminder has to be its own timed event."""
        user_id, trip_id = _setup(test_db)
        reminders = _find(_events(_export(test_db, user_id, trip_id)), "SUMMARY:Check out:")
        assert len(reminders) == 1
        assert "BEGIN:VALARM" in reminders[0]
        assert "TRIGGER:-PT1H" in reminders[0]

    def test_reminder_is_not_zero_length(self, test_db):
        """Several clients render a zero-length timed event as nothing at all."""
        user_id, trip_id = _setup(test_db)
        reminder = _find(_events(_export(test_db, user_id, trip_id)), "SUMMARY:Check out:")[0]
        # 11:00 Lisbon, floating — the hour the property actually asks you to
        # be out — and the block runs 30 minutes past it.
        assert _require(reminder, "DTSTART") == "20261008T110000"
        assert _require(reminder, "DTEND") == "20261008T113000"

    def test_uids_are_distinct(self, test_db):
        user_id, trip_id = _setup(test_db)
        events = _events(_export(test_db, user_id, trip_id))
        uids = [_require(e, "UID") for e in events]
        assert len(uids) == len(set(uids))


class TestCalendarSpan:
    def test_the_span_event_covers_a_stays_only_trip(self, test_db):
        user_id, trip_id = _setup(test_db)
        span = _find(_events(_export(test_db, user_id, trip_id)), "UID:")
        span = [e for e in span if _require(e, "UID").endswith("-span@partiu")]
        assert len(span) == 1
        assert _require(span[0], "DTSTART").startswith("20261004")
        assert _require(span[0], "DTEND").startswith("20261008")
