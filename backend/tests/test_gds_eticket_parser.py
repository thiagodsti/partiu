"""
Test: airline-independent GDS electronic-ticket receipt parser.

Fixture:
  tap_eticket_multileg_anonymized.json
    A five-leg Amadeus ITR-EMD receipt (TAP-issued) with a connection in each
    direction and a codeshare leg operated by another carrier:
      TP781  ARN→LIS, 22 Dec 2026 14:20 → 17:55   (terminals 2 / 1)
      TP109  LIS→FLN, 23 Dec 2026 11:05 → 19:10   (terminal 1 / none printed)
      TP8130 FLN→GRU, 15 Jan 2027 11:15 → 12:35   (none printed / terminal 2)
      TP82   GRU→LIS, 15 Jan 2027 16:20 → 16 Jan 05:15  (terminals 3 / 1)
      TP780  LIS→ARN, 16 Jan 2027 08:05 → 13:30   (terminals 1 / 2)
    Booking reference: TESTRF (anonymized)

This fixture is the regression case for three separate defects:
  * the receipt has legs *without* a printed terminal, which the old TAP-specific
    pattern required, so it matched nothing and fell through to the line scanner;
  * the line scanner then resolved city names by unranked substring search,
    inventing Nyköping (NYO) for "STOCKHOLM" and Ponta Delgada (PDL) for
    "SAO PAULO" — the airport whose name contains "João **Paulo** II";
  * it also read the "NVA"/"NVB" not-valid-before/after labels as airport codes
    (NVA is Neiva, Colombia).
"""

from datetime import UTC, datetime

import pytest
from conftest import load_anonymized_fixture


def dt(year, month, day, hour, minute) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


@pytest.fixture(scope="module")
def eticket_email():
    return load_anonymized_fixture("tap_eticket_multileg_anonymized.json")


@pytest.fixture(scope="module")
def eticket_flights(eticket_email, seeded_airports_db):
    from backend.parsers.gds_eticket import extract_gds_eticket

    return extract_gds_eticket(eticket_email)


class TestDetection:
    def test_recognises_receipt_marker(self):
        from backend.parsers.gds_eticket import looks_like_gds_eticket

        assert looks_like_gds_eticket("RECIBO DE BILHETE ELETRONICO")

    def test_recognises_english_marker(self):
        from backend.parsers.gds_eticket import looks_like_gds_eticket

        assert looks_like_gds_eticket("Your ELECTRONIC TICKET RECEIPT is attached")

    def test_ignores_unrelated_email(self):
        from backend.parsers.gds_eticket import looks_like_gds_eticket

        assert not looks_like_gds_eticket("Your flight is delayed")

    def test_non_receipt_email_yields_nothing(self, seeded_airports_db):
        from backend.parsers.email_connector import EmailMessage
        from backend.parsers.gds_eticket import extract_gds_eticket

        msg = EmailMessage(
            message_id="x",
            sender="a@b.c",
            subject="Sale",
            body="Cheap flights this week",
            date=datetime.now(tz=UTC),
            html_body="<html><body><p>Cheap flights</p></body></html>",
        )
        assert extract_gds_eticket(msg) == []


class TestLegCount:
    def test_all_five_legs_extracted(self, eticket_flights):
        assert len(eticket_flights) == 5

    def test_no_leg_repeats_an_airport_pair_wrongly(self, eticket_flights):
        routes = [(f["departure_airport"], f["arrival_airport"]) for f in eticket_flights]
        assert routes == [
            ("ARN", "LIS"),
            ("LIS", "FLN"),
            ("FLN", "GRU"),
            ("GRU", "LIS"),
            ("LIS", "ARN"),
        ]


class TestFlightNumbers:
    def test_flight_numbers_in_travel_order(self, eticket_flights):
        assert [f["flight_number"] for f in eticket_flights] == [
            "TP781",
            "TP109",
            "TP8130",
            "TP82",
            "TP780",
        ]

    def test_four_digit_flight_number_kept_intact(self, eticket_flights):
        # TP8130 is a codeshare on a partner carrier; the marketing number stands
        assert eticket_flights[2]["flight_number"] == "TP8130"


class TestAirportResolution:
    def test_stockholm_resolves_to_arlanda_not_skavsta(self, eticket_flights):
        assert eticket_flights[0]["departure_airport"] == "ARN"

    def test_sao_paulo_resolves_to_guarulhos_not_ponta_delgada(self, eticket_flights):
        assert eticket_flights[2]["arrival_airport"] == "GRU"

    def test_leg_without_printed_terminal_still_resolves(self, eticket_flights):
        # Florianópolis prints no terminal — the old pattern required one
        assert eticket_flights[1]["arrival_airport"] == "FLN"

    def test_no_label_text_became_an_airport(self, eticket_flights):
        codes = {f["departure_airport"] for f in eticket_flights}
        codes |= {f["arrival_airport"] for f in eticket_flights}
        # NVA/NVB/NVD are "not valid before/after" labels, not airports
        assert codes == {"ARN", "LIS", "FLN", "GRU"}

    def test_route_chains_end_to_end(self, eticket_flights):
        for previous, following in zip(eticket_flights, eticket_flights[1:], strict=False):
            assert previous["arrival_airport"] == following["departure_airport"]


class TestDatetimes:
    def test_first_departure(self, eticket_flights):
        assert eticket_flights[0]["departure_datetime"] == dt(2026, 12, 22, 14, 20)

    def test_first_arrival(self, eticket_flights):
        assert eticket_flights[0]["arrival_datetime"] == dt(2026, 12, 22, 17, 55)

    def test_outbound_connection_next_day(self, eticket_flights):
        assert eticket_flights[1]["departure_datetime"] == dt(2026, 12, 23, 11, 5)

    def test_return_legs_use_the_printed_year(self, eticket_flights):
        # Return travel is in January of the *following* year
        assert eticket_flights[2]["departure_datetime"] == dt(2027, 1, 15, 11, 15)

    def test_overnight_leg_arrives_next_day(self, eticket_flights):
        assert eticket_flights[3]["departure_datetime"] == dt(2027, 1, 15, 16, 20)
        assert eticket_flights[3]["arrival_datetime"] == dt(2027, 1, 16, 5, 15)

    def test_last_leg(self, eticket_flights):
        assert eticket_flights[4]["departure_datetime"] == dt(2027, 1, 16, 8, 5)
        assert eticket_flights[4]["arrival_datetime"] == dt(2027, 1, 16, 13, 30)


class TestTerminals:
    def test_departure_terminal_is_the_number_not_the_label(self, eticket_flights):
        # The cell reads "Terminal / Terminal: 2" in two languages
        assert eticket_flights[0]["departure_terminal"] == "2"

    def test_arrival_terminal(self, eticket_flights):
        assert eticket_flights[0]["arrival_terminal"] == "1"

    def test_missing_terminal_is_empty(self, eticket_flights):
        assert eticket_flights[1]["arrival_terminal"] == ""


class TestBookingReference:
    def test_booking_reference_on_every_leg(self, eticket_flights):
        assert all(f["booking_reference"] == "TESTRF" for f in eticket_flights)


class TestExtractionOrder:
    """The GDS parser and the airline rules are the only structural extractors
    left in the pipeline; nothing may reintroduce a generic line scanner behind
    them.

    Those scanners keyed off proximity to a flight number rather than table
    position, so on this receipt they read the "NVA" not-valid-after label as an
    airport (Neiva, Colombia) and missed a leg entirely. Little of that was
    caught by the plausibility gate — FLN→NVA in 8h05 is a perfectly ordinary
    speed — which is why the tier was removed rather than reordered.
    """

    def test_pipeline_has_no_generic_scanner_tier(self, eticket_email, seeded_airports_db):
        import inspect

        from backend.parsers import engine
        from backend.sync import pipeline

        source = inspect.getsource(pipeline._process_emails)
        assert "extract_gds_eticket" in source
        for banned in ("try_generic_html_extraction", "try_generic_pdf_extraction"):
            assert banned not in source, f"{banned} must not run in the sync pipeline"
            assert not hasattr(engine, banned), f"engine.{banned} must not exist"

    def test_receipt_from_an_airline_without_a_rule_still_parses(
        self, eticket_email, seeded_airports_db
    ):
        from backend.parsers.builtin_rules import get_builtin_rules
        from backend.parsers.engine import match_rule_to_email
        from backend.parsers.gds_eticket import extract_gds_eticket

        unmatched = load_anonymized_fixture("tap_eticket_multileg_anonymized.json")
        unmatched.sender = "Ops <no-reply@carrier-with-no-rule.example>"
        assert match_rule_to_email(unmatched, get_builtin_rules()) is None

        flights = extract_gds_eticket(unmatched, None)
        assert len(flights) == 5
        assert flights[0]["departure_airport"] == "ARN"
        assert flights[0]["arrival_airport"] == "LIS"

    def test_airline_code_inferred_when_no_rule_matched(self, seeded_airports_db):
        from backend.parsers.gds_eticket import extract_gds_eticket

        unmatched = load_anonymized_fixture("tap_eticket_multileg_anonymized.json")
        unmatched.sender = "Ops <no-reply@carrier-with-no-rule.example>"
        flights = extract_gds_eticket(unmatched, None)
        assert flights[0]["airline_code"] == "TP"


class TestCompactPdfLayout:
    """The second GDS rendering: the itinerary arrives as a PDF attachment and
    the HTML part is only a cover note, so there is no table to read.

    Fixture: sas_eticket_pdf_anonymized.eml — an Amadeus "Electronic Ticket
    Itinerary and Receipt" with legs written one per line::

        AF 871 / 12NOV  Cape Town - Paris CDG          07:55 19:15
        AF 1462 / 12NOV Paris CDG - Stockholm Arlanda  21:00 23:40  Terminal 2F
    """

    @pytest.fixture(scope="class")
    def compact_flights(self, seeded_airports_db):
        from conftest import load_eml_as_email_message

        from backend.parsers.gds_eticket import extract_gds_eticket

        return extract_gds_eticket(load_eml_as_email_message("sas_eticket_pdf_anonymized.eml"))

    def test_both_legs_extracted(self, compact_flights):
        assert len(compact_flights) == 2

    def test_flight_numbers(self, compact_flights):
        assert [f["flight_number"] for f in compact_flights] == ["AF871", "AF1462"]

    def test_routes_resolved_from_city_names(self, compact_flights):
        assert [(f["departure_airport"], f["arrival_airport"]) for f in compact_flights] == [
            ("CPT", "CDG"),
            ("CDG", "ARN"),
        ]

    def test_multiword_city_name_not_truncated(self, compact_flights):
        # "Stockholm Arlanda" must survive the route split intact
        assert compact_flights[1]["arrival_airport"] == "ARN"

    def test_times(self, compact_flights):
        assert compact_flights[0]["departure_datetime"].strftime("%H:%M") == "07:55"
        assert compact_flights[0]["arrival_datetime"].strftime("%H:%M") == "19:15"

    def test_trailing_terminal_belongs_to_arrival(self, compact_flights):
        assert compact_flights[1]["arrival_terminal"] == "2F"

    def test_leg_without_terminal_is_empty(self, compact_flights):
        assert compact_flights[0]["arrival_terminal"] == ""

    def test_booking_reference(self, compact_flights):
        assert all(f["booking_reference"] for f in compact_flights)

    def test_table_layout_still_preferred_when_present(self, eticket_flights):
        """A receipt with a real table must not fall through to the text path."""
        assert eticket_flights[0]["departure_terminal"] == "2"


class TestReceiptDateYearResolution:
    """Compact-layout dates carry no year ("28OCT"). A ticket receipt is issued
    when the ticket is bought, so its flights are on or after the issue date —
    injecting the email's year lands a year early across New Year."""

    def test_year_less_date_rolls_forward_past_the_issue_date(self):
        from datetime import UTC, datetime

        from backend.parsers.gds_eticket import _resolve_receipt_date

        issued = datetime(2024, 12, 6, tzinfo=UTC)
        resolved = _resolve_receipt_date("28OCT", issued)
        assert resolved is not None
        assert resolved.year == 2025

    def test_date_after_issue_keeps_the_issue_year(self):
        from datetime import UTC, datetime

        from backend.parsers.gds_eticket import _resolve_receipt_date

        issued = datetime(2025, 5, 15, tzinfo=UTC)
        resolved = _resolve_receipt_date("28OCT", issued)
        assert resolved is not None
        assert resolved.year == 2025

    def test_explicit_year_is_never_shifted(self):
        from datetime import UTC, datetime

        from backend.parsers.gds_eticket import _resolve_receipt_date

        issued = datetime(2026, 9, 9, tzinfo=UTC)
        resolved = _resolve_receipt_date("22Dec2020", issued)
        assert resolved is not None
        assert resolved.year == 2020

    def test_same_day_as_issue_is_not_rolled(self):
        from datetime import UTC, datetime

        from backend.parsers.gds_eticket import _resolve_receipt_date

        issued = datetime(2025, 10, 28, tzinfo=UTC)
        resolved = _resolve_receipt_date("28OCT", issued)
        assert resolved is not None
        assert resolved.year == 2025

    def test_no_reference_date_falls_back_to_plain_parsing(self):
        from backend.parsers.gds_eticket import _resolve_receipt_date

        assert _resolve_receipt_date("28OCT", None) is not None

    def test_unparseable_token(self):
        from datetime import UTC, datetime

        from backend.parsers.gds_eticket import _resolve_receipt_date

        assert _resolve_receipt_date("not-a-date", datetime(2025, 1, 1, tzinfo=UTC)) is None


class TestMergeWithAirlineRule:
    """An airline rule can quietly miss legs on a multi-carrier itinerary, so the
    pipeline merges GDS results in rather than treating them as a fallback."""

    def test_merge_appends_legs_the_rule_missed(self):
        from backend.parsers.engine import merge_flights

        rule_result = [
            {"flight_number": "VS449", "departure_airport": "LHR", "arrival_airport": "JNB"}
        ]
        gds_result = [
            {"flight_number": "KL1220", "departure_airport": "ARN", "arrival_airport": "AMS"},
            {"flight_number": "VS449", "departure_airport": "LHR", "arrival_airport": "JNB"},
        ]
        merged = merge_flights(rule_result, gds_result)
        assert len(merged) == 2
        assert {f["flight_number"] for f in merged} == {"VS449", "KL1220"}

    def test_agreeing_parsers_do_not_duplicate(self):
        from backend.parsers.engine import merge_flights

        same = [{"flight_number": "TP781", "departure_airport": "ARN", "arrival_airport": "LIS"}]
        merged = merge_flights([dict(same[0])], [dict(same[0])])
        assert len(merged) == 1

    def test_rule_fields_survive_the_merge(self):
        from backend.parsers.engine import merge_flights

        rule_result = [
            {
                "flight_number": "TP781",
                "departure_airport": "ARN",
                "arrival_airport": "LIS",
                "seat": "12A",
            }
        ]
        gds_result = [
            {
                "flight_number": "TP781",
                "departure_airport": "ARN",
                "arrival_airport": "LIS",
                "seat": "",
                "arrival_terminal": "1",
            }
        ]
        merged = merge_flights(rule_result, gds_result)
        assert merged[0]["seat"] == "12A"  # rule's value not overwritten
        assert merged[0]["arrival_terminal"] == "1"  # GDS fills the gap

    def test_pipeline_merges_rather_than_falling_back(self):
        import inspect

        from backend.sync import pipeline

        source = inspect.getsource(pipeline._process_emails)
        assert "merge_flights(flights_data, gds_flights)" in source


class TestIataPairCorroboration:
    def test_collects_pairs_from_baggage_block(self):
        from backend.parsers.gds_eticket import collect_iata_pairs

        pairs = collect_iata_pairs("CARRY-ON BAG: ARNLIS: MAX 1PC LISFLN: MAX 1PC")
        assert ("ARN", "LIS") in pairs
        assert ("LIS", "FLN") in pairs

    def test_ignores_a_repeated_code(self):
        from backend.parsers.gds_eticket import collect_iata_pairs

        assert ("ARN", "ARN") not in collect_iata_pairs("ARNARN")

    def test_fills_a_missing_half_when_unambiguous(self):
        from backend.parsers.gds_eticket import _pick_corroborated_route

        assert _pick_corroborated_route("ARN", "", [("ARN", "LIS")]) == ("ARN", "LIS")

    def test_refuses_to_guess_when_ambiguous(self):
        from backend.parsers.gds_eticket import _pick_corroborated_route

        pairs = [("ARN", "LIS"), ("ARN", "CPH")]
        assert _pick_corroborated_route("ARN", "", pairs) == ("ARN", "")

    def test_never_overrides_a_confident_pair(self):
        from backend.parsers.gds_eticket import _pick_corroborated_route

        assert _pick_corroborated_route("ARN", "LIS", [("GRU", "CPH")]) == ("ARN", "LIS")


# ---------------------------------------------------------------------------
# Amadeus fixed-column layout (the ITR as plain text in a <pre>)
# ---------------------------------------------------------------------------
# Fixture: tap_eticket_columnar_anonymized.json
#   TP783  ARN→LIS, 10 Nov 2023 19:05 → 22:35   (terminals 5 / 1)
#   TP780  LIS→ARN, 18 Nov 2023 08:05 → 13:30   (terminals 1 / 5)
#   Issued 09 Aug 2023; booking reference TESTRF ("BOOKING REF : AMADEUS: TESTRF")
# Place names are truncated to the column ("STOCKHOLM ARLAN"), so the route
# is settled by the baggage block's bare pairs (ARNLIS / LISARN).


@pytest.fixture(scope="module")
def columnar_email():
    return load_anonymized_fixture("tap_eticket_columnar_anonymized.json")


@pytest.fixture(scope="module")
def columnar_flights(columnar_email, seeded_airports_db):
    from backend.parsers.gds_eticket import extract_gds_eticket

    return extract_gds_eticket(columnar_email)


class TestColumnarLayout:
    def test_both_legs(self, columnar_flights):
        assert [
            (f["flight_number"], f["departure_airport"], f["arrival_airport"])
            for f in columnar_flights
        ] == [
            ("TP783", "ARN", "LIS"),
            ("TP780", "LIS", "ARN"),
        ]

    def test_times_and_forward_resolved_dates(self, columnar_flights):
        assert columnar_flights[0]["departure_datetime"] == dt(2023, 11, 10, 19, 5)
        assert columnar_flights[0]["arrival_datetime"] == dt(2023, 11, 10, 22, 35)
        assert columnar_flights[1]["departure_datetime"] == dt(2023, 11, 18, 8, 5)
        assert columnar_flights[1]["arrival_datetime"] == dt(2023, 11, 18, 13, 30)

    def test_terminals(self, columnar_flights):
        assert (
            columnar_flights[0]["departure_terminal"],
            columnar_flights[0]["arrival_terminal"],
        ) == ("5", "1")
        assert (
            columnar_flights[1]["departure_terminal"],
            columnar_flights[1]["arrival_terminal"],
        ) == ("1", "5")

    def test_booking_reference_is_the_locator_not_the_gds_name(self, columnar_flights):
        assert {f["booking_reference"] for f in columnar_flights} == {"TESTRF"}

    def test_reaches_the_same_result_through_the_tap_rule(self, columnar_email, seeded_airports_db):
        from backend.parsers.builtin_rules import get_builtin_rules
        from backend.parsers.engine import extract_flights_from_email, match_rule_to_email

        rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
        rule = match_rule_to_email(columnar_email, rules)
        assert rule is not None and rule.airline_code == "TP"
        assert [f["flight_number"] for f in extract_flights_from_email(columnar_email, rule)] == [
            "TP783",
            "TP780",
        ]

    def test_a_repeated_block_is_read_once(self, columnar_email, seeded_airports_db):
        """The real mail carries the receipt twice — fixed-width text and a
        whitespace-collapsed copy of the HTML — in one body."""
        import re as _re

        from backend.parsers.email_connector import EmailMessage
        from backend.parsers.gds_eticket import extract_gds_eticket

        collapsed = _re.sub(r"[ \t]+", " ", columnar_email.body)
        doubled = EmailMessage(
            message_id="x",
            sender=columnar_email.sender,
            subject=columnar_email.subject,
            body=columnar_email.body + "\n" + collapsed,
            date=columnar_email.date,
            html_body=None,
        )
        assert [f["flight_number"] for f in extract_gds_eticket(doubled)] == ["TP783", "TP780"]

    def test_header_line_is_not_a_leg(self):
        from backend.parsers.gds_eticket import _COLUMNAR_LEG_RE

        assert (
            _COLUMNAR_LEG_RE.search(
                "FROM /TO        FLIGHT  CL DATE  DEP      FARE BASIS    NVB   NVA   BAG ST\n"
            )
            is None
        )
