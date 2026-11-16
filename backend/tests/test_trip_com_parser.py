"""
Test: Trip.com hotel booking-confirmation parser.

Fixture: tests/fixtures/trip_com_hotel_confirmation_anonymized.json
  Houhaiyuan Hotel (Beijing Gongwangfu Nanluoguxiang Branch),
  No. 7 Qianjing Hutong, Xicheng District, Beijing, China
  Check-in 24 Mar 2027 (after 14:00), check-out 27 Mar 2027 (before 12:00)
  Guest Room (Double Bed); Booking no. 1234567890123456

Trip.com ships no schema.org markup, so this template reader is the only way
its hotel confirmations become stays. The synthetic cases cover the gates and
the places where the mail's own wording looks like a field.
"""

from datetime import UTC, datetime

import pytest
from conftest import load_anonymized_fixture

from backend.parsers.trip_com import extract_trip_com_stays

SENDER = '"Trip.com" <EN_HTL_NoReply@trip.com>'
SUBJECT = "[Booking confirmation] Your booking at Test Harbour Hotel has been confirmed-NoReply"

# The line layout ``html_to_text`` gives the real template, with invented values.
TEXT = """\
Booking No.
1‌111‌222‌333
Hi Test Passenger! The booking for your stay in Porto is confirmed.
Your stay at Test Harbour Hotel (check-in: Jun 4, 2027, check-out: Jun 7, 2027) is confirmed
Free cancellation - Before 18:00, Jun 4, 2027 (Hotel's local time)
Hotel confirmation number: 999888777
Booking no.
1111222333
Test Harbour Hotel
Call+351000000000
Booking details
Check-in
Jun 4, 2027
After 15:00
Hotel's local time
Check-out
Jun 7, 2027
Before 11:00
Hotel's local time
Your booking
1 Room 3 nights
Address
1 Example Street, Porto, Portugal
Cancellation policy
Free cancellation
Before 18:00, Jun 4, 2027
Twin Room with Sea View
1 Room 3 nights
Guest names
Test Passenger
"""


class _Email:
    def __init__(self, body=TEXT, sender=SENDER, subject=SUBJECT):
        self.body = body
        self.html_body = None
        self.sender = sender
        self.subject = subject
        self.date = datetime(2027, 1, 1, tzinfo=UTC)


@pytest.fixture(scope="module")
def trip_email():
    return load_anonymized_fixture("trip_com_hotel_confirmation_anonymized.json")


class TestRealConfirmation:
    def test_reads_the_stay(self, trip_email):
        (stay,) = extract_trip_com_stays(trip_email)
        assert stay["name"] == "Houhaiyuan Hotel (Beijing Gongwangfu Nanluoguxiang Branch)"
        assert stay["city"] == "Beijing"
        assert stay["contact"] == "+86-13121869867"
        assert stay["room_type"] == "Guest Room (Double Bed)"

    def test_times_are_the_after_and_the_before(self, trip_email):
        (stay,) = extract_trip_com_stays(trip_email)
        assert stay["check_in_datetime"] == "2027-03-24T14:00"
        assert stay["check_out_datetime"] == "2027-03-27T12:00"

    def test_reference_is_the_platform_booking_number(self, trip_email):
        """Not the "Hotel confirmation number" printed beside it."""
        (stay,) = extract_trip_com_stays(trip_email)
        assert stay["booking_reference"] == "1234567890123456"

    def test_address_leaves_out_the_local_script_line(self, trip_email):
        (stay,) = extract_trip_com_stays(trip_email)
        assert stay["address"] == "No. 7 Qianjing Hutong, Xicheng District, Beijing, China"

    def test_country_and_guests_are_not_guessed(self, trip_email):
        """The country is a name inside the address and the template lists only
        the names entered at booking, so neither is turned into a fact."""
        (stay,) = extract_trip_com_stays(trip_email)
        assert stay["country_code"] is None
        assert stay["guests"] is None


class TestSyntheticTemplate:
    def test_reads_every_field(self):
        (stay,) = extract_trip_com_stays(_Email())
        assert stay["name"] == "Test Harbour Hotel"
        assert stay["check_in_datetime"] == "2027-06-04T15:00"
        assert stay["check_out_datetime"] == "2027-06-07T11:00"
        assert stay["booking_reference"] == "1111222333"
        assert stay["address"] == "1 Example Street, Porto, Portugal"
        assert stay["city"] == "Porto"
        assert stay["contact"] == "+351000000000"

    def test_summary_count_line_is_not_the_room(self):
        """ "1 Room 3 nights" also follows "Your booking" in the summary; the room
        is the line above the count that sits over "Guest names"."""
        (stay,) = extract_trip_com_stays(_Email())
        assert stay["room_type"] == "Twin Room with Sea View"

    def test_zero_width_header_number_is_not_needed(self):
        text = TEXT.replace("Booking no.\n1111222333\n", "")
        (stay,) = extract_trip_com_stays(_Email(text))
        assert stay["booking_reference"] == "1111222333"

    def test_name_falls_back_to_the_stay_at_line(self):
        (stay,) = extract_trip_com_stays(_Email(subject="[Booking confirmation] Trip.com"))
        assert stay["name"] == "Test Harbour Hotel"

    def test_missing_times_use_the_defaults(self):
        text = TEXT.replace("After 15:00\n", "").replace("Before 11:00\n", "")
        (stay,) = extract_trip_com_stays(_Email(text))
        assert stay["check_in_datetime"] == "2027-06-04T14:00"
        assert stay["check_out_datetime"] == "2027-06-07T11:00"


class TestGates:
    def test_other_senders_are_ignored(self):
        assert extract_trip_com_stays(_Email(sender="hotel@example.com")) == []

    def test_a_cancellation_is_not_imported(self):
        email = _Email(subject="[Booking cancelled] Your booking at Test Harbour Hotel")
        assert extract_trip_com_stays(email) == []

    def test_free_cancellation_in_the_body_is_not_a_cancellation(self):
        assert len(extract_trip_com_stays(_Email())) == 1

    def test_a_non_confirmation_subject_yields_nothing(self):
        email = _Email(subject="Your trip to Porto is coming up")
        assert extract_trip_com_stays(email) == []

    def test_no_details_block_yields_nothing(self):
        text = TEXT.replace("Booking details\n", "")
        assert extract_trip_com_stays(_Email(text)) == []

    def test_check_out_before_check_in_is_refused(self):
        text = TEXT.replace("Jun 7, 2027\nBefore", "Jun 1, 2027\nBefore")
        assert extract_trip_com_stays(_Email(text)) == []
