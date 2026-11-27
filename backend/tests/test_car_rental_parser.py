"""Tests for `parsers/car_rental.py` — Hertz, Sixt, Europcar and Booking.com.

Structures are copied from the real mails; every reference, name, place and
vehicle is invented. The three vendors lay their fields out one per line in
the plain-text part; Booking.com's broker mail is HTML, read through
`html_to_text`, with the supplier named in a labelled field.

The case worth knowing about is `TestEuropcarDateOrder`: Europcar prints
"8/24/19" with no month name to settle the order, and guessing wrong moves a
booking by months rather than failing visibly.
"""

import uuid
from datetime import UTC, datetime

from conftest import load_eml_as_email_message

from backend.parsers.car_rental import (
    extract_car_rentals,
    is_booking_com_car_sender,
    is_car_rental_sender,
)


class _Email:
    def __init__(self, sender, body="", subject="", html_body=""):
        self.sender = sender
        self.body = body
        self.subject = subject
        self.html_body = html_body
        self.message_id = f"<{uuid.uuid4()}@example.com>"
        self.date = datetime(2024, 3, 5, tzinfo=UTC)
        self.pdf_attachments = []


HERTZ_BODY = """My Hertz Reservation

Confirmation

X11223344Y

Hi

Sample Traveller,

Thank you for your reservation with Hertz.

Mini, 2-3 Door, Manual, Air

(A) Fiat 500

or similar

Total

$351.51 USD

Your Trip Itinerary

Pickup Location

Vienna Airport

Schwechat Airport

Vienna,

AT
1300

Pickup Date & Time

Fri, Mar 29, 2024 at 09:30 AM

Location Hours

Mo-Fr 0700-2330, Sa 0800-2000, Su 0800-2300

Drop-off Location

Vienna Airport

Schwechat Airport

Vienna,

AT
1300

Drop-off Date & Time

Mon, Apr 01, 2024 at 11:00 PM

Location Hours

Mo-Fr 0700-2330
"""

SIXT_BODY = """
 Reservation:

 8800112233


 Great choice, Sample


 YOUR RESERVATION IS CONFIRMED

Pickup at Munich Airport

   Friday, Mar 29, 2024 at 1:30 pm


 Return at Vienna-Schwechat  Airport

   Monday, Apr 01, 2024 at 8:30 pm

Vehicle category
Opel Mokka or similar
Automatic

Mileage

 Unlimited kilometers included

 Total paid in advance

 513,85 €
"""

EUROPCAR_BODY = """Europcar Confirmation Email

Thank you for choosing
Europcar
Your booking is confirmed
Your booking or reservation number is:
9900112233
Manage your booking
Driver details
Drivers:
SAMPLE TRAVELLER
Pick-up
TRAPANI AIRPORT
8/24/19 8:00 AM
Station details and map
Return
CATANIA AIRPORT (SICILY)
8/24/19 12:30 PM
Station details
Duration:
1
day
MC FORFOUR 70 1.0 (MCMR) or similar
Mini
"""


class TestSenderGate:
    def test_the_three_vendors_are_recognised(self):
        assert is_car_rental_sender("reservations@emails.hertz.com") == "Hertz"
        assert is_car_rental_sender("reservierung@sixt.com") == "Sixt"
        assert is_car_rental_sender("no-reply@europcar.com") == "Europcar"

    def test_anyone_else_is_not(self):
        assert is_car_rental_sender("noreply@flysas.com") == ""
        assert is_car_rental_sender("") == ""

    def test_an_unknown_vendor_yields_nothing(self):
        """No generic tier: a rental mail is mostly price breakdown and terms,
        and anchoring on "a date near the word pickup" invents bookings."""
        email = _Email("bookings@avis.com", body=HERTZ_BODY)
        assert extract_car_rentals(email) == []


class TestForwardedConfirmation:
    def test_the_original_vendor_header_is_used(self):
        body = (
            "---------- Forwarded message ---------\n"
            "From: reservations@emails.hertz.com\n"
            "Subject: My Hertz Reservation\n\n"
            f"{HERTZ_BODY}"
        )
        email = _Email("traveller@example.com", body=body, subject="Fwd")
        assert extract_car_rentals(email) == [
            {
                "vendor": "Hertz",
                "booking_reference": "X11223344Y",
                "pickup_place": "Vienna Airport",
                "pickup_datetime": "2024-03-29T09:30",
                "dropoff_place": "Vienna Airport",
                "dropoff_datetime": "2024-04-01T23:00",
                "vehicle": "Fiat 500 or similar",
            }
        ]

    def test_no_vendor_header_means_no_rental(self):
        email = _Email("traveller@example.com", body=HERTZ_BODY, subject="Fwd: My Hertz Reservation")
        assert extract_car_rentals(email) == []


class TestHertz:
    def test_reads_the_whole_booking(self):
        email = _Email("reservations@emails.hertz.com", body=HERTZ_BODY)
        assert extract_car_rentals(email) == [
            {
                "vendor": "Hertz",
                "booking_reference": "X11223344Y",
                "pickup_place": "Vienna Airport",
                "pickup_datetime": "2024-03-29T09:30",
                "dropoff_place": "Vienna Airport",
                "dropoff_datetime": "2024-04-01T23:00",
                "vehicle": "Fiat 500 or similar",
            }
        ]

    def test_pm_is_read_as_afternoon(self):
        """11:00 PM is 23:00, not 11:00 — the drop-off in the real mail."""
        rental = extract_car_rentals(_Email("reservations@emails.hertz.com", body=HERTZ_BODY))[0]
        assert rental["dropoff_datetime"].endswith("T23:00")

    def test_the_vehicle_group_code_is_dropped(self):
        """ "(A) Fiat 500" — the "(A)" is Hertz's own class letter and means
        nothing to the traveller."""
        rental = extract_car_rentals(_Email("reservations@emails.hertz.com", body=HERTZ_BODY))[0]
        assert rental["vehicle"] == "Fiat 500 or similar"

    def test_the_country_line_is_not_mistaken_for_a_place(self):
        """Hertz prints a bare "AT" two lines under the location label."""
        rental = extract_car_rentals(_Email("reservations@emails.hertz.com", body=HERTZ_BODY))[0]
        assert rental["pickup_place"] == "Vienna Airport"

    def test_a_truncated_mail_yields_nothing(self):
        email = _Email("reservations@emails.hertz.com", body="Confirmation\n\nX11223344Y\n")
        assert extract_car_rentals(email) == []


class TestSixt:
    def test_reads_a_one_way_booking(self):
        """Munich to Vienna — the shape that rules out collapsing a rental to
        a single place."""
        email = _Email("reservierung@sixt.com", body=SIXT_BODY)
        assert extract_car_rentals(email) == [
            {
                "vendor": "Sixt",
                "booking_reference": "8800112233",
                "pickup_place": "Munich Airport",
                "pickup_datetime": "2024-03-29T13:30",
                "dropoff_place": "Vienna-Schwechat Airport",
                "dropoff_datetime": "2024-04-01T20:30",
                "vehicle": "Opel Mokka or similar",
            }
        ]

    def test_the_double_space_in_a_station_name_is_collapsed(self):
        rental = extract_car_rentals(_Email("reservierung@sixt.com", body=SIXT_BODY))[0]
        assert rental["dropoff_place"] == "Vienna-Schwechat Airport"

    def test_a_full_weekday_name_is_stripped(self):
        """Sixt writes "Friday", Hertz writes "Fri" — both reach the same
        date parser."""
        rental = extract_car_rentals(_Email("reservierung@sixt.com", body=SIXT_BODY))[0]
        assert rental["pickup_datetime"].startswith("2024-03-29")


class TestEuropcar:
    def test_reads_the_whole_booking(self):
        email = _Email("no-reply@europcar.com", body=EUROPCAR_BODY)
        assert extract_car_rentals(email) == [
            {
                "vendor": "Europcar",
                "booking_reference": "9900112233",
                "pickup_place": "TRAPANI AIRPORT",
                "pickup_datetime": "2019-08-24T08:00",
                "dropoff_place": "CATANIA AIRPORT (SICILY)",
                "dropoff_datetime": "2019-08-24T12:30",
                "vehicle": "MC FORFOUR 70 1.0 (MCMR) or similar",
                "driver_name": "SAMPLE TRAVELLER",
            }
        ]


class TestBookingCom:
    """The broker mail from ``cars.booking.com`` — HTML, and the supplier is a
    field rather than the sender."""

    BUDGET = load_eml_as_email_message("booking_car_budget_anonymized.eml")
    ENTERPRISE = load_eml_as_email_message("booking_car_enterprise_anonymized.eml")

    def test_the_broker_sender_is_recognised(self):
        assert is_booking_com_car_sender("no-reply@cars.booking.com")
        assert not is_booking_com_car_sender("no-reply@booking.com")
        assert is_car_rental_sender("no-reply@cars.booking.com") == ""

    def test_reads_a_same_location_booking_from_the_html_part(self):
        assert extract_car_rentals(self.BUDGET) == [
            {
                "vendor": "Budget",
                "booking_reference": "BOOKINGREF123",
                "pickup_place": "Malaga Airport",
                "pickup_datetime": "2026-12-19T11:30",
                "dropoff_place": "Malaga Airport, Malaga, Spain, 29004",
                "dropoff_datetime": "2026-12-26T19:30",
                "vehicle": "Volkswagen Taigo or similar",
                "driver_name": "Test Driver",
            }
        ]

    def test_reads_a_one_way_booking_and_a_folded_subject(self):
        """The Enterprise subject folds between "Airport" and "is confirmed"."""
        assert extract_car_rentals(self.ENTERPRISE) == [
            {
                "vendor": "Enterprise",
                "booking_reference": "BOOKINGREF456",
                "pickup_place": "Gdansk Lech Walesa Airport",
                "pickup_datetime": "2026-10-16T11:00",
                "dropoff_place": "Gdansk Lech Walesa Airport, Gdansk, Poland, 80-298",
                "dropoff_datetime": "2026-10-19T16:00",
                "vehicle": "Peugeot 208 or similar",
                "driver_name": "Test Driver",
            }
        ]

    def test_a_forward_uses_the_original_sender_and_subject(self):
        email = _Email(
            "traveller@example.com",
            body=(
                "---------- Forwarded message ---------\n"
                "From: Booking.com <no-reply@cars.booking.com>\n"
                "Subject: Thanks! Your car rental with Budget at Malaga Airport is confirmed\n\n"
            ),
            subject="Fwd",
            html_body=self.BUDGET.html_body,
        )
        rentals = extract_car_rentals(email)
        assert [r["vendor"] for r in rentals] == ["Budget"]

    def test_a_forward_with_a_wrapped_from_header_is_read(self):
        """A real Gmail forward printed "From:", then "Booking.com", then the
        address on its own line. Reading only the label's line found no domain,
        so the broker gate refused the mail and no rental was ever imported.
        """
        email = _Email(
            "traveller@example.com",
            body=(
                "---------- Forwarded message ---------\n"
                "From:\n"
                "Booking.com\n"
                "<no-reply@cars.booking.com>\n"
                "Date: Fri, 13 Nov 2026 14:36:29 +0000\n"
                "Subject:\n"
                "Thanks! Your car rental with Budget at Malaga Airport is confirmed\n"
                "To: <traveller@example.com>\n"
            ),
            subject="Fwd",
            html_body=self.BUDGET.html_body,
        )
        assert [r["vendor"] for r in extract_car_rentals(email)] == ["Budget"]

    def test_a_cancellation_is_not_a_booking(self):
        email = _Email(
            "no-reply@cars.booking.com",
            subject="Your car rental with Budget at Malaga Airport is cancelled",
            html_body=self.BUDGET.html_body,
        )
        assert extract_car_rentals(email) == []

    def test_an_empty_confirmation_does_not_swallow_the_next_label(self):
        """The line under `Confirmation:` can be another label in a variant of
        the template; a phone number is not a booking reference."""
        html = self.BUDGET.html_body.replace("<div>BOOKINGREF123</div>", "")
        email = _Email(
            "no-reply@cars.booking.com",
            subject=self.BUDGET.subject,
            html_body=html,
        )
        assert "booking_reference" not in extract_car_rentals(email)[0]

    def test_an_unknown_broker_layout_yields_nothing(self):
        """No proximity tier: the labels have to be the ones this reader knows."""
        html = self.BUDGET.html_body.replace("Rental company", "Supplier")
        email = _Email(
            "no-reply@cars.booking.com",
            subject=self.BUDGET.subject,
            html_body=html,
        )
        assert extract_car_rentals(email) == []


class TestEuropcarDateOrder:
    """ "8/24/19" has no month name to settle the order, and guessing wrong moves
    a booking by months rather than failing visibly. The two dates come from one
    template, so a single unambiguous component decides both."""

    def test_a_middle_component_over_twelve_means_month_first(self):
        rental = extract_car_rentals(_Email("no-reply@europcar.com", body=EUROPCAR_BODY))[0]
        assert rental["pickup_datetime"].startswith("2019-08-24")

    def test_a_leading_component_over_twelve_means_day_first(self):
        body = EUROPCAR_BODY.replace("8/24/19 8:00 AM", "24/8/19 8:00 AM").replace(
            "8/24/19 12:30 PM", "24/8/19 12:30 PM"
        )
        rental = extract_car_rentals(_Email("no-reply@europcar.com", body=body))[0]
        assert rental["pickup_datetime"].startswith("2019-08-24")

    def test_one_unambiguous_date_settles_its_ambiguous_twin(self):
        """Pickup 5/6 is ambiguous alone; the drop-off's 24 settles both."""
        body = EUROPCAR_BODY.replace("8/24/19 8:00 AM", "6/5/19 8:00 AM").replace(
            "8/24/19 12:30 PM", "6/24/19 12:30 PM"
        )
        rental = extract_car_rentals(_Email("no-reply@europcar.com", body=body))[0]
        assert rental["pickup_datetime"].startswith("2019-06-05")
        assert rental["dropoff_datetime"].startswith("2019-06-24")

    def test_an_impossible_date_yields_nothing_rather_than_a_guess(self):
        body = EUROPCAR_BODY.replace("8/24/19 8:00 AM", "13/32/19 8:00 AM")
        assert extract_car_rentals(_Email("no-reply@europcar.com", body=body)) == []


class TestRobustness:
    def test_an_empty_body_yields_nothing(self):
        assert extract_car_rentals(_Email("reservations@emails.hertz.com", body="")) == []

    def test_a_marketing_mail_from_a_rental_vendor_yields_nothing(self):
        email = _Email(
            "offers@sixt.com",
            body="Spring sale! Book a car from 19 EUR a day. Terms apply.",
        )
        assert extract_car_rentals(email) == []

    def test_a_booking_with_no_place_named_is_refused(self):
        """A rental with one end guessed is worse than no rental at all."""
        body = SIXT_BODY.replace("Return at Vienna-Schwechat  Airport", "Return at")
        assert extract_car_rentals(_Email("reservierung@sixt.com", body=body)) == []
