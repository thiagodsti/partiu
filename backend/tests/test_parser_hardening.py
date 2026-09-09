"""
Tests for the cross-cutting parser fixes made when the generic line scanners were
removed. Each of these was masking (or causing) a wrong flight in the DB.
"""

from datetime import UTC, datetime

import pytest


def _rule(name: str, code: str):
    return type("Rule", (), {"airline_name": name, "airline_code": code})()


def _email(*, sender="", subject="", body="", html="", date=None):
    from backend.parsers.email_connector import EmailMessage

    return EmailMessage(
        message_id="hardening-test",
        sender=sender,
        subject=subject,
        body=body,
        date=date or datetime(2024, 5, 16, tzinfo=UTC),
        html_body=html,
        pdf_attachments=[],
    )


# ---------------------------------------------------------------------------
# Localised forwarded-message headers
# ---------------------------------------------------------------------------


class TestLocalisedForwardedHeaders:
    """Gmail localises the forwarded-message labels to the *forwarder's* UI
    language, not the original sender's. Matching only "From:" meant a Brazilian
    user forwarding a Ryanair itinerary reached no airline rule at all.
    """

    @staticmethod
    def _forwarded(label: str, address: str, subject_label: str = "Subject") -> str:
        return (
            "---------- Forwarded message ---------\n"
            f"{label}: <{address}>\n"
            "Date: qui., 16 de mai. de 2024 às 11:46\n"
            f"{subject_label}: Ryanair Travel Itinerary\n"
            "To: <someone@gmail.com>\n"
        )

    @pytest.mark.parametrize(
        "label",
        ["From", "De", "Von", "Från", "Fra", "Da", "Van", "Expéditeur", "Remitente"],
    )
    def test_sender_label_variants_are_read(self, label):
        from backend.parsers.engine import _extract_forwarded_senders

        body = self._forwarded(label, "Itinerary@ryanair.com")
        assert any("ryanair.com" in s for s in _extract_forwarded_senders(body))

    @pytest.mark.parametrize(
        "label", ["Subject", "Assunto", "Asunto", "Betreff", "Ämne", "Oggetto"]
    )
    def test_subject_label_variants_are_read(self, label):
        from backend.parsers.engine import _extract_forwarded_subjects

        body = self._forwarded("De", "Itinerary@ryanair.com", subject_label=label)
        assert any("Ryanair" in s for s in _extract_forwarded_subjects(body))

    def test_forwarded_email_reaches_the_airline_rule(self):
        from backend.parsers.builtin_rules import get_builtin_rules
        from backend.parsers.engine import match_rule_to_email

        rules = sorted(get_builtin_rules(), key=lambda r: (-r.priority, r.airline_name))
        msg = _email(
            sender="Someone <someone@gmail.com>",
            subject="Fwd: Ryanair Travel Itinerary",
            body=self._forwarded("De", "Itinerary@ryanair.com"),
        )
        rule = match_rule_to_email(msg, rules)
        assert rule is not None
        assert rule.airline_code == "FR"


# ---------------------------------------------------------------------------
# Subject-keyword coverage
# ---------------------------------------------------------------------------


class TestSubjectPatternCoverage:
    @pytest.mark.parametrize(
        "subject",
        [
            "Resehandlingar Ref. QAJV6E",
            "Bokningsbekräftelse och information för TWJRQF",
            "Booking details | Departure: 29 March 2024 | ARN-MUC",
        ],
    )
    def test_subject_is_accepted(self, subject):
        import re

        from backend.parsers.builtin_rules import SUBJECT_PATTERN

        assert re.search(SUBJECT_PATTERN, subject, re.IGNORECASE), subject

    def test_norwegian_travel_docs_reaches_its_rule(self):
        """Regression: "Resehandlingar" matched no subject keyword, so the DY rule
        never ran and the generic scanner produced both legs pointing one way."""
        from backend.parsers.builtin_rules import get_builtin_rules
        from backend.parsers.engine import match_rule_to_email

        rules = sorted(get_builtin_rules(), key=lambda r: (-r.priority, r.airline_name))
        msg = _email(
            sender='"Norwegian.se" <noreply@norwegian.se>', subject="Resehandlingar Ref. QAJV6E"
        )
        rule = match_rule_to_email(msg, rules)
        assert rule is not None
        assert rule.airline_code == "DY"


# ---------------------------------------------------------------------------
# scan_flights: lookbehind must not borrow the previous leg's arrival airport
# ---------------------------------------------------------------------------


class TestScanFlightsLookbehind:
    """The two lines of lookbehind exist for layouts that print the route above
    the flight number, but on a multi-leg itinerary they also reach back into the
    previous leg's arrival airport — which read a Ryanair round trip as
    "BCN → BCN" and dropped the return leg for having equal endpoints.
    """

    ROUND_TRIP = "\n".join(
        [
            "Reservation:",
            "BRFIMH",
            "To Barcelona",
            "FR3077",
            "ARN -",
            "Barcelona",
            "Fri, 12 Jul 24",
            "Departure time -",
            "10:10",
            "Arrival time -",
            "13:45",
            "(ARN) -",
            "(BCN)",
            "To ARN",
            "FR3076",
            "Barcelona -",
            "ARN",
            "Fri, 19 Jul 24",
            "Departure time -",
            "05:55",
            "Arrival time -",
            "09:35",
            "(BCN) -",
            "(ARN)",
        ]
    )

    @pytest.fixture(scope="class")
    def flights(self, seeded_airports_db):
        from backend.parsers.shared import scan_flights

        return scan_flights(self.ROUND_TRIP, _rule("Ryanair", "FR"), 2024)

    def test_both_legs_extracted(self, flights):
        assert len(flights) == 2

    def test_outbound_route(self, flights):
        assert (flights[0]["departure_airport"], flights[0]["arrival_airport"]) == ("ARN", "BCN")

    def test_return_route_not_collapsed(self, flights):
        """Regression: the return leg used to come out as BCN → BCN and be dropped."""
        assert (flights[1]["departure_airport"], flights[1]["arrival_airport"]) == ("BCN", "ARN")

    def test_route_above_the_flight_number_still_works(self, seeded_airports_db):
        """Single-leg layouts that only state the route *before* the flight number
        must keep working — the lookbehind is still consulted when needed."""
        from backend.parsers.shared import scan_flights

        text = "\n".join(
            [
                "(ARN)",
                "(LHR)",
                "SK533",
                "Fri, 12 Jul 24",
                "Departure time -",
                "10:10",
                "Arrival time -",
                "11:45",
            ]
        )
        flights = scan_flights(text, _rule("SAS", "SK"), 2024)
        assert len(flights) == 1
        assert (flights[0]["departure_airport"], flights[0]["arrival_airport"]) == ("ARN", "LHR")


# ---------------------------------------------------------------------------
# make_flight_dict: the single choke point for flight-number sanity
# ---------------------------------------------------------------------------


class TestFlightNumberValidation:
    @staticmethod
    def _build(fn: str):
        from backend.parsers.shared import make_flight_dict

        return make_flight_dict(
            _rule("SAS", "SK"),
            fn,
            "ARN",
            "LHR",
            datetime(2024, 5, 1, 10, 0, tzinfo=UTC),
            datetime(2024, 5, 1, 11, 45, tzinfo=UTC),
        )

    @pytest.mark.parametrize("fn", ["SK533", "W65362", "4U1234", "LH9", "AY0806"])
    def test_valid_flight_numbers_accepted(self, fn, seeded_airports_db):
        assert self._build(fn) is not None

    @pytest.mark.parametrize("fn", ["A320neo", "ECONOMY", "TERMINAL", "SK", "533"])
    def test_implausible_tokens_rejected(self, fn, seeded_airports_db):
        assert self._build(fn) is None


class TestSasAircraftTypeNotReadAsFlightNumber:
    """SAS prints "SK1829 | Airbus A320neo" — and "A3" (Aegean) is in its
    codeshare prefix list, so every leg gained a phantom "A320" duplicate."""

    HTML = (
        "<html><body>"
        "<p>07 August 2020</p>"
        "<p>ARN - Stockholm Arlanda NCE</p>"
        "<p>14:55 - 17:05</p>"
        "<p>SK1829 | Airbus A320neo</p>"
        "</body></html>"
    )

    def test_no_phantom_aircraft_type_leg(self, seeded_airports_db):
        from backend.parsers.airlines.sas import extract_bs4

        msg = _email(html=self.HTML, subject="Your Flight, Booking: [QQFWDG]")
        flights = extract_bs4(self.HTML, _rule("SAS Scandinavian Airlines", "SK"), msg)
        assert "A320" not in [f["flight_number"] for f in flights]

    def test_bounded_pattern_rejects_embedded_match(self):
        import re

        from backend.parsers.airlines.sas import _FLIGHT_NUM_BOUNDED

        assert re.search(_FLIGHT_NUM_BOUNDED, "Airbus A320neo") is None
        assert re.search(_FLIGHT_NUM_BOUNDED, "A3 456") is not None
        assert re.search(_FLIGHT_NUM_BOUNDED, "SK1829") is not None


# ---------------------------------------------------------------------------
# The generic tier is gone and must stay gone
# ---------------------------------------------------------------------------


class TestGenericScannersRemoved:
    def test_generic_html_module_is_gone(self):
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("backend.parsers.generic_html")

    @pytest.mark.parametrize(
        "name",
        ["try_generic_html_extraction", "try_generic_pdf_extraction", "_extract_generic_pdf"],
    )
    def test_engine_no_longer_exposes_generic_entry_points(self, name):
        from backend.parsers import engine

        assert not hasattr(engine, name)

    def test_rule_result_is_returned_verbatim_even_with_a_pdf_attached(self):
        """PDF reading is each rule's own business (or the GDS parser's). The
        generic PDF pattern contributed nothing across the whole email corpus
        while remaining able to invent a leg from any itinerary-shaped table, so
        nothing is merged in behind the rule's back any more."""
        from backend.parsers.engine import extract_flights_from_email

        sentinel = [{"flight_number": "SK533"}]
        rule = _rule("SAS", "SK")
        rule.extractor = lambda email_msg, r: sentinel

        msg = _email(subject="Booking", body="irrelevant")
        # A PDF the old generic pass would have scanned for extra "legs"
        msg.pdf_attachments = [b"%PDF-1.4 not a real pdf"]

        assert extract_flights_from_email(msg, rule) == sentinel
