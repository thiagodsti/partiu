"""
Test: Booking.com booking-confirmation parser.

Fixture: tests/fixtures/booking_com_confirmation_anonymized.json
  B&B HOTEL Lisboa Aeroporto, Rua Vasco da Gama 5, 2685-244 Lisbon, Portugal
  Check-in 22 Dec 2026 (14:00 - 00:00), check-out 23 Dec 2026 (until 12:00)
  1 night, Double Room, 1 adult; Confirmation: 1234567890

Booking.com ships no schema.org markup, so this template reader is the only way
its confirmations become stays. The synthetic cases cover the text/plain
rendering (label and value on one line), the gates, and the two places the
mail's own wording looks like a field label.
"""

from datetime import UTC, datetime

import pytest
from conftest import load_anonymized_fixture

from backend.parsers.booking_com import extract_booking_com_stays

SENDER = "noreply@booking.com"
SUBJECT = "Thanks! Your booking is confirmed at Test Harbour Hotel"

# The text/plain rendering of the real template, filled with invented values.
PLAIN = """\
   Booking.com
   Confirmation: 9876543210
   PIN: 0000 (Confidential)

Thanks Test! Your booking in Porto is confirmed.

   [checkmark.png] Test Harbour Hotel is expecting you on Fri 4
   Jun

Test Harbour Hotel

Your reservation is paid with Booking.com

   No further payment is required before the stay.

Reservation details

   Check-in Friday, 4 June 2027 (15:00 - 23:00)
   Check-out Monday, 7 June 2027 (until 11:00)
   Your reservation 3 nights, Twin Room with Sea View
   You booked for 2 adults, 1 child
   Location


    1 Example Street, 4000-000 Porto, Portugal

   Phone +351000000000
   Contact Email property
   Cancellation policy
   Free cancellation until 2 June 2027.

Important Details

     * Guests are required to show a photo identification upon check-in
       on 1 January 2027 at 09:00.
"""


class _Email:
    def __init__(self, body="", html_body=None, sender=SENDER, subject=SUBJECT):
        self.body = body
        self.html_body = html_body
        self.sender = sender
        self.subject = subject
        self.date = datetime(2027, 1, 1, tzinfo=UTC)


@pytest.fixture(scope="module")
def booking_email():
    return load_anonymized_fixture("booking_com_confirmation_anonymized.json")


class TestRealConfirmation:
    def test_reads_the_stay(self, booking_email):
        (stay,) = extract_booking_com_stays(booking_email)
        assert stay["name"] == "B&B HOTEL Lisboa Aeroporto"
        assert stay["address"] == "Rua Vasco da Gama 5, 2685-244 Lisbon, Portugal"
        assert stay["city"] == "Lisbon"
        assert stay["booking_reference"] == "1234567890"
        assert stay["contact"] == "+351211626726"

    def test_times_are_the_window_start_and_the_until(self, booking_email):
        """Check-in prints a window "(14:00 - 00:00)" — its start is the time;
        check-out prints "(until 12:00)"."""
        (stay,) = extract_booking_com_stays(booking_email)
        assert stay["check_in_datetime"] == "2026-12-22T14:00"
        assert stay["check_out_datetime"] == "2026-12-23T12:00"

    def test_room_and_guests(self, booking_email):
        (stay,) = extract_booking_com_stays(booking_email)
        assert stay["room_type"] == "Double Room"
        assert stay["guests"] == 1

    def test_country_name_is_not_turned_into_a_code(self, booking_email):
        """The mail prints "Portugal", never "PT"; the importer's geocode
        supplies the code rather than this parser guessing it."""
        (stay,) = extract_booking_com_stays(booking_email)
        assert stay["country_code"] is None

    def test_the_payment_banner_is_not_the_room_field(self, booking_email):
        """ "Your reservation is paid with Booking.com" opens with the room
        field's label and sits above the Reservation details block."""
        (stay,) = extract_booking_com_stays(booking_email)
        assert "paid" not in stay["room_type"]


class TestPrice:
    def test_the_total_includes_vat_and_city_tax(self, booking_email):
        """ "Total price" € 69.23, not the € 63.90 room rate above it nor the
        € 67.73 cancellation cost."""
        (stay,) = extract_booking_com_stays(booking_email)
        assert stay["price"] == (69.23, "EUR")

    def test_no_total_means_no_price(self):
        (stay,) = extract_booking_com_stays(_Email(PLAIN))
        assert stay["price"] is None


class TestPlainTextRendering:
    def test_label_and_value_on_one_line(self):
        """Also proves the small print's "… upon check-in on 1 January 2027 at
        09:00" is not read as the check-in: the label must open its line."""
        (stay,) = extract_booking_com_stays(_Email(PLAIN))
        assert stay["check_in_datetime"] == "2027-06-04T15:00"
        assert stay["check_out_datetime"] == "2027-06-07T11:00"
        assert stay["room_type"] == "Twin Room with Sea View"
        assert stay["guests"] == 3
        assert stay["address"] == "1 Example Street, 4000-000 Porto, Portugal"
        assert stay["booking_reference"] == "9876543210"
        assert stay["city"] == "Porto"

    def test_name_falls_back_to_the_expecting_line(self):
        (stay,) = extract_booking_com_stays(_Email(PLAIN, subject="Booking.com"))
        assert stay["name"] == "Test Harbour Hotel"

    def test_missing_times_use_the_defaults(self):
        text = PLAIN.replace(" (15:00 - 23:00)", "").replace(" (until 11:00)", "")
        (stay,) = extract_booking_com_stays(_Email(text))
        assert stay["check_in_datetime"] == "2027-06-04T14:00"
        assert stay["check_out_datetime"] == "2027-06-07T11:00"


class TestGates:
    def test_other_senders_are_ignored(self):
        assert extract_booking_com_stays(_Email(PLAIN, sender="hotel@example.com")) == []

    def test_a_cancellation_is_not_imported(self):
        email = _Email(PLAIN, subject="Your booking at Test Harbour Hotel is cancelled")
        assert extract_booking_com_stays(email) == []

    def test_special_request_mail_is_not_a_confirmation(self):
        """Properties write through property.booking.com, restating the dates
        with no address and no times."""
        text = (
            "Confirmation number: 3000000000\n"
            "You got a message about your request\n"
            "Reservation Details\nCheck-in:\nSat, Jul 16, 2022\n"
            "Check-out:\nTue, Jul 19, 2022\nProperty Name:\nTest Hotel\n"
        )
        email = _Email(
            text,
            sender='"Test Hotel via Booking.com" <3000000000-abcd@property.booking.com>',
            subject="Special Request for your Reservation 3000000000",
        )
        assert extract_booking_com_stays(email) == []

    def test_no_details_block_yields_nothing(self):
        text = PLAIN.split("Reservation details")[0]
        assert extract_booking_com_stays(_Email(text)) == []

    def test_check_out_before_check_in_is_refused(self):
        text = PLAIN.replace("Monday, 7 June 2027", "Monday, 1 June 2027")
        assert extract_booking_com_stays(_Email(text)) == []


class TestForwardedConfirmation:
    """An autoforward arrives From: the traveller, with the real booking headers
    quoted in the body. The airline rules have always coped with that; the
    template readers used to stop at the envelope sender.
    """

    @staticmethod
    def _forwarded(original_subject: str) -> str:
        return (
            "---------- Forwarded message ---------\n"
            f"From: {SENDER}\n"
            f"Subject: {original_subject}\n"
            "Date: Fri, 1 Jan 2027 10:00:00 +0000\n"
            "To: traveller@example.com\n\n"
            f"{PLAIN}"
        )

    def test_the_original_sender_and_subject_are_used(self):
        email = _Email(
            self._forwarded(SUBJECT),
            sender="traveller@example.com",
            subject="Fwd: Booking",
        )
        (stay,) = extract_booking_com_stays(email)
        assert stay["name"] == "Test Harbour Hotel"
        assert stay["booking_reference"] == "9876543210"
        assert stay["check_in_datetime"] == "2027-06-04T15:00"

    def test_a_forwarded_cancellation_is_still_not_imported(self):
        email = _Email(
            self._forwarded("Your booking at Test Harbour Hotel is cancelled"),
            sender="traveller@example.com",
            subject="Fwd",
        )
        assert extract_booking_com_stays(email) == []

    def test_a_forwarder_with_no_booking_com_header_is_ignored(self):
        email = _Email(PLAIN, sender="traveller@example.com", subject="Fwd: Booking")
        assert extract_booking_com_stays(email) == []
