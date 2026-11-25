"""parsers/booking_signal.may_describe_a_flight: the gate in front of the LLM.

It replaced the blocked-sender list (migration 0042), so these pin both halves
of that bargain: real flight mail from any sender gets through, and the mail the
list used to stop (lodging, tickets, appointments with no flight number) does
not.
"""

from backend.parsers.booking_signal import may_describe_a_flight


class TestMayDescribeAFlight:
    def test_a_confirmation_from_an_airline_with_no_rule(self):
        assert may_describe_a_flight(
            "Sua passagem foi emitida com sucesso - e-ticket: PVNQDY",
            "Código da reserva: PVNQDY\nVoo G3 1234  GRU 07:10 → FLN 08:25",
        )

    def test_the_reference_label_alone_is_enough_with_a_flight_number(self):
        # Subject says nothing (a forwarded GDS receipt), the body does.
        assert may_describe_a_flight(
            "DINIZDASILVEIRA/THIAGOMR 10NOV ARN LIS",
            "BOOKING REF: ABC123\nTP 783  10NOV  ARN 19:05  LIS 22:35",
        )

    def test_a_flight_number_only_in_the_subject_counts(self):
        # Lufthansa's check-in mail names the flight in the subject; the body
        # is mostly a button.
        assert may_describe_a_flight(
            "Your flight LH247 Milan - Frankfurt/Main is now ready for Check-in",
            "Check in now",
        )

    def test_a_lodging_confirmation_has_no_flight_number(self):
        assert not may_describe_a_flight(
            "Reservation confirmed - Lisbon, 22 Dec",
            "Your reservation is confirmed. Confirmation code HMABC12345. Check-in 15:00.",
        )

    def test_marketing_is_vetoed_even_with_a_flight_number(self):
        assert not may_describe_a_flight(
            "Get an upgrade for your flight to GRU",
            "Booking reference XYZ123 — LA 8072 — upgrade now for 15% less",
        )

    def test_a_flight_number_without_any_booking_context_is_not_enough(self):
        assert not may_describe_a_flight(
            "Your order has shipped",
            "Order AB 1234 is on its way.",
        )

    def test_missing_fields_are_fine(self):
        assert not may_describe_a_flight(None, None)
        assert not may_describe_a_flight("", "")

    def test_swedish_and_turkish_booking_words(self):
        assert may_describe_a_flight("Din bokning", "Bokningsnummer QAJV6E\nDY 4371 ARN-OSL")
        assert may_describe_a_flight("Rezervasyonun onaylandı!", "PC 1234 SAW → ADB")

    def test_smiles_is_a_booking_not_miles_marketing(self):
        # GOL's loyalty programme is called Smiles; "miles" must match a whole
        # word or its e-ticket mail never reaches the LLM.
        assert may_describe_a_flight(
            "Smiles - Sua passagem foi emitida",
            "Código da reserva: PVNQDY\nVoo G3 1234 GRU 07:10 FLN 08:25",
        )
        assert not may_describe_a_flight(
            "Earn double miles on your next flight",
            "Booking reference XYZ123 — LA 8072",
        )


class TestLooksLikeFlightBooking:
    """The strict test for the review list: subject about a booking, a flight
    number and a reference label, no marketing."""

    def test_a_missed_booking(self):
        from backend.parsers.booking_signal import looks_like_flight_booking

        assert looks_like_flight_booking(
            "Sua passagem foi emitida com sucesso",
            "Código da reserva: PVNQDY\nNúmero do voo: O66175",
        )

    def test_a_check_in_reminder_is_not_a_booking(self):
        from backend.parsers.booking_signal import looks_like_flight_booking

        # Passes the LLM gate (check-in, flight number) but is about a flight
        # that is, in practice, already stored.
        assert not looks_like_flight_booking(
            "Check-in is open for your flight", "Booking reference ABC123, LH 803"
        )

    def test_all_three_signals_are_required(self):
        from backend.parsers.booking_signal import looks_like_flight_booking

        assert not looks_like_flight_booking("Your booking", "Thanks for booking with us")
        assert not looks_like_flight_booking("Your booking", "Booking reference ABC123")
