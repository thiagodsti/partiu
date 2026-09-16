"""Tests for cancellation extraction and for applying it to stored flights.

Before this existed, cancellation was handled only by *suppressing* extraction —
`austrian.extract` returns [] on a cancellation subject, `finnair.extract` bails
on its cancellation notice. That stops a dead leg being created and does nothing
about the leg already stored from the booking confirmation weeks earlier.
Measured across the 372-email corpus, six cancellation mails matched an airline
rule, produced nothing, and left phantom flights behind.

The trap this file exists to pin is `test_a_schedule_change_is_not_a_cancellation`:
SAS's schedule-change mail carries its own booking reference *and* the sentence
"Cancel your booking" — as one of three options being offered to the traveller.
Matching the word "cancel" there would strike off a booking that is merely being
moved, and the itinerary is not reprinted anywhere in that mail, so nothing would
ever put it back.
"""

import uuid
from datetime import UTC, datetime

from backend.parsers.cancellations import booking_cancellation, leg_cancellation


class _Email:
    def __init__(self, subject="", body="", html_body="", sender="", date=None):
        self.subject = subject
        self.body = body
        self.html_body = html_body
        self.sender = sender
        self.message_id = f"<{uuid.uuid4()}@example.com>"
        self.date = date or datetime(2024, 3, 26, 17, 26, tzinfo=UTC)
        self.pdf_attachments = []


# Structures copied from the real mails; every reference, name and route invented.

SAS_CANCELLATION = """Dear Traveler,

You have now cancelled your trip.

Booking reference:  QQ7RTX

SAS will make the refund instantly and return the amount to the same form of
payment used for purchase.
"""

# The dangerous one. Real SAS schedule-change mail: names the booking, offers
# cancelling as an option, and reprints no itinerary at all.
SAS_SCHEDULE_CHANGE = """Important information about your SAS booking QQ7RTX

Dear Traveler,
Unfortunately, we've had to change our flight schedule which has impacted your
trip with booking reference QQ7RTX.
Please see our suggested new itinerary in My Bookings.

You now have three options:
Travel on the new flight(s) we provide as an alternative
Rebook to a new flight, free of charge
Cancel your booking
If you choose not to travel, you can cancel your booking and get a refund.
"""

LH_CANCELLATION = """Cancellation Confirmation

Lufthansa booking code:
ZZ4MV9

Passenger information
TRAVELLER/SAMPLE MR

Unfortunately we had to cancel your booking on 09 November 2021.

Best regards,
Your Lufthansa team
"""

AY_CANCELLATION = """Bekräftelse på din avbokning
Din bokning har avbokats
Cancelled booking reference:
WWJRQ8
MR Sample Traveller
Du har avbokat din bokning.
Inställda flyg:
Utresa 2024-07-29
Stockholm Arlanda - Helsingfors Helsinki Vantaa
AY806
"""

OS_CANCELLATION_SUBJECT = "Cancellation of your flight OS318 Stockholm - Vienna on 29.3.2024"
OS_CANCELLATION = """Flight cancellation - we are looking for alternatives for you

Your Austrian flight has been cancelled

Dear Mr. Traveller,

Your Austrian flight OS318 from Stockholm to Vienna on 29.3.2024 has been cancelled.
Please accept our sincere apologies.
"""


class TestRecordShapes:
    """`cancellations.py` refuses anything it cannot act on, rather than handing
    the pipeline a record it would have to second-guess."""

    def test_a_booking_reference_is_normalised(self):
        assert booking_cancellation(" qq7rtx ") == {"booking_reference": "QQ7RTX"}

    def test_a_cancellation_naming_no_booking_is_refused(self):
        # There is no safe way to guess which of the traveller's flights an
        # unidentified cancellation meant.
        assert booking_cancellation("") is None
        assert booking_cancellation("nope, not a reference") is None

    def test_a_leg_needs_both_a_number_and_a_date(self):
        assert leg_cancellation("OS318", "2024-03-29") == {
            "flight_number": "OS318",
            "departure_date": "2024-03-29",
        }
        # A flight number with no date would cancel every instance of a route
        # the traveller has ever flown.
        assert leg_cancellation("OS318", "") is None
        assert leg_cancellation("", "2024-03-29") is None
        assert leg_cancellation("OS318", "29.3.2024") is None


class TestSas:
    def test_reports_the_cancelled_booking(self):
        from backend.parsers.airlines.sas import extract_cancellations

        email = _Email(subject="Cancellation Confirmation", body=SAS_CANCELLATION)
        assert extract_cancellations(email) == [{"booking_reference": "QQ7RTX"}]

    def test_the_refund_wording_is_also_recognised(self):
        from backend.parsers.airlines.sas import extract_cancellations

        email = _Email(subject="Cancellation and refund confirmation", body=SAS_CANCELLATION)
        assert extract_cancellations(email) == [{"booking_reference": "QQ7RTX"}]

    def test_a_schedule_change_is_not_a_cancellation(self):
        """The whole reason the SAS marker is past tense.

        This mail names its booking reference and contains the words "cancel
        your booking" — as an option on offer. Reading it as a cancellation
        would strike off a trip that is still going ahead, and since the mail
        reprints no itinerary, nothing would ever restore it.
        """
        from backend.parsers.airlines.sas import extract_cancellations

        email = _Email(
            subject="Schedule change from SAS - Booking reference QQ7RTX",
            body=SAS_SCHEDULE_CHANGE,
        )
        assert extract_cancellations(email) == []


class TestLufthansa:
    def test_reports_the_cancelled_booking_code(self):
        from backend.parsers.airlines.lufthansa import extract_cancellations

        email = _Email(subject="Cancellation Confirmation", body=LH_CANCELLATION)
        assert extract_cancellations(email) == [{"booking_reference": "ZZ4MV9"}]

    def test_an_ordinary_confirmation_reports_nothing(self):
        from backend.parsers.airlines.lufthansa import extract_cancellations

        email = _Email(
            subject="Your booking confirmation",
            body="Lufthansa booking code:\nZZ4MV9\nThank you for booking with us.",
        )
        assert extract_cancellations(email) == []


class TestFinnair:
    def test_reports_the_booking_not_the_listed_legs(self):
        """The mail lists AY806 under "Inställda flyg", but the reference above
        covers the same set and survives the layout changing. Narrowing to the
        legs that happen to parse could under-cancel a booking."""
        from backend.parsers.airlines.finnair import extract_cancellations

        email = _Email(subject="Bekräftelse på din avbokning", body=AY_CANCELLATION)
        assert extract_cancellations(email) == [{"booking_reference": "WWJRQ8"}]


class TestAustrian:
    def test_reports_one_leg_not_the_whole_booking(self):
        """Austrian cancels a single flight. The same reference holds the return
        leg, which this mail says nothing about — it is explicitly about finding
        an alternative for *this* flight."""
        from backend.parsers.airlines.austrian import extract_cancellations

        email = _Email(subject=OS_CANCELLATION_SUBJECT, body=OS_CANCELLATION)
        assert extract_cancellations(email) == [
            {"flight_number": "OS318", "departure_date": "2024-03-29"}
        ]

    def test_the_leg_is_reported_once_though_it_appears_twice(self):
        """The subject and the body both state the cancellation; without
        de-duplication the one leg would be reported two times."""
        from backend.parsers.airlines.austrian import extract_cancellations

        email = _Email(subject=OS_CANCELLATION_SUBJECT, body=OS_CANCELLATION)
        assert len(extract_cancellations(email)) == 1

    def test_a_travel_confirmation_reports_nothing(self):
        from backend.parsers.airlines.austrian import extract_cancellations

        email = _Email(
            subject="Your Travel Confirmation, departure 03 Apr 24",
            body="Your Austrian flight OS318 from Stockholm to Vienna on 29.3.2024.",
        )
        assert extract_cancellations(email) == []


class TestRuleBinding:
    def test_the_four_airlines_are_bound_and_the_rest_are_not(self):
        """`cancellation_extractor` is resolved the same dynamic way `extract`
        and `boarding_pass_extractor` are — an airline opts in by defining the
        function, and absence is not an error."""
        from backend.parsers.builtin_rules import get_builtin_rules

        bound = {
            r.custom_extractor
            for r in get_builtin_rules()
            if getattr(r, "cancellation_extractor", None) is not None
        }
        assert bound == {"sas", "lufthansa", "finnair", "austrian"}
