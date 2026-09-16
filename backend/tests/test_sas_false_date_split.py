"""Regression test: a SAS terminal number must not be read as a date.

`extract_bs4` splits the flattened email into one block per date, and its
`date_re` accepts "<1-2 digits> <word> <4 digits>". SAS flattens a leg to

    ... 07:30 - 09:10 ( 1h 40m ) Avgångsterminal 5 SK 2601 | Canadair ...

in which "5 SK 2601" matches that shape perfectly — 5 the day, SK the month,
2601 the year. Splitting the block there strands the route and the times in one
block and the flight number in the next, so neither block can build a leg and
the whole itinerary vanishes silently.

The reason this went unnoticed is that it needs *both* conditions: a four-digit
flight number (SK 525 is too short for `\\d{4}`) and no **arrival** terminal
(with one, the text reads "... 5 - Ankomstterminal 2 SK 2601" and the digit
adjacent to the flight number is the arrival terminal, breaking the match).
Both hold on exactly one email in the 372-message corpus, and its legs happened
to be recorded elsewhere too — so nothing was visibly lost, and a mailbox where
that mail is the only source would have lost the trip outright.
"""

import re

import pytest

from backend.parsers.airlines.sas import _FLIGHT_NUM_BOUNDED, extract_bs4
from backend.parsers.builtin_rules import get_builtin_rules
from backend.parsers.engine import parse_flight_date


class _Email:
    subject = "Din flygning [on 10 maj 2023], Bokning :[TESTREF]"
    sender = "SAS <no-reply@flysas.com>"
    body = ""
    html_body = ""


def _leg(date, dep_city, dep_iata, arr_city, arr_iata, dep_t, arr_t, dur, flight, terminals):
    return f"""
      <div>{dep_city}</div><div>{dep_iata}</div><div>-</div>
      <div>{arr_city}</div><div>{arr_iata}</div>
      <div>{date}</div>
      <div>{dep_t}</div><div>-</div><div>{arr_t}</div><div>({dur}, Direktflyg)</div>
      <div>SAS Go Light</div>
      <div>{dep_city}</div><div>{dep_iata}</div><div>-</div>
      <div>{arr_city}</div><div>{arr_iata}</div>
      <div>{dep_t}</div><div>-</div><div>{arr_t}</div><div>( {dur} )</div>
      {terminals}
      <div>{flight}</div><div>|</div><div>Canadair Regional Jet 900</div><div>|</div><div>Xfly</div>
      <div>Bokningsklass</div><div>O</div>
    """


def _html(terminals_out, terminals_home):
    return (
        "<html><body><div>Bokningsref TESTREF</div><div>UTRESA</div>"
        + _leg(
            "10 May 2023",
            "Stockholm",
            "ARN",
            "Warsaw",
            "WAW",
            "07:30",
            "09:10",
            "1h 40m",
            "SK 2601",
            terminals_out,
        )
        + "<div>HEMRESA</div>"
        + _leg(
            "14 May 2023",
            "Warsaw",
            "WAW",
            "Stockholm",
            "ARN",
            "18:30",
            "20:15",
            "1h 45m",
            "SK 2604",
            terminals_home,
        )
        + "</body></html>"
    )


DEPARTURE_TERMINAL_ONLY = "<div>Avgångsterminal</div><div>5</div>"
BOTH_TERMINALS = (
    "<div>Avgångsterminal</div><div>5</div><div>-</div><div>Ankomstterminal</div><div>2</div>"
)


@pytest.fixture
def rule():
    return next(r for r in get_builtin_rules() if r.airline_code == "SK")


class TestFalseDateSplit:
    def test_a_four_digit_flight_after_a_lone_terminal_still_parses(self, rule):
        """The exact shape that was silently dropping whole itineraries."""
        flights = extract_bs4(
            _html(DEPARTURE_TERMINAL_ONLY, DEPARTURE_TERMINAL_ONLY), rule, _Email()
        )
        by_number = {f["flight_number"]: f for f in flights}
        assert set(by_number) == {"SK2601", "SK2604"}
        assert by_number["SK2601"]["departure_airport"] == "ARN"
        assert by_number["SK2601"]["arrival_airport"] == "WAW"
        assert by_number["SK2604"]["departure_airport"] == "WAW"
        assert by_number["SK2604"]["arrival_airport"] == "ARN"

    def test_both_terminals_present_still_parses(self, rule):
        """The variant that always worked — by luck, not by design."""
        flights = extract_bs4(_html(BOTH_TERMINALS, BOTH_TERMINALS), rule, _Email())
        assert {f["flight_number"] for f in flights} == {"SK2601", "SK2604"}

    def test_a_three_digit_flight_number_still_parses(self, rule):
        """SK 525 was never affected: 525 is too short for the year group."""
        html = (
            _html(DEPARTURE_TERMINAL_ONLY, DEPARTURE_TERMINAL_ONLY)
            .replace("SK 2601", "SK 525")
            .replace("SK 2604", "SK 528")
        )
        flights = extract_bs4(html, rule, _Email())
        assert {f["flight_number"] for f in flights} == {"SK525", "SK528"}


class TestTheUnderlyingShape:
    """Pin the trap itself, so tightening `date_re` later cannot resurrect it."""

    DATE_RE = re.compile(r"(?:^|\s)(\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+\d{4})(?:\s|$)")

    def test_terminal_plus_flight_number_looks_like_a_date(self):
        assert self.DATE_RE.search(" Avgångsterminal 5 SK 2601 |") is not None

    def test_but_parse_flight_date_rejects_it(self):
        """Which is why filtering on `parse_flight_date` is the fix — it is
        already the multilingual authority on what a date is."""
        assert parse_flight_date("5 SK 2601") is None
        assert parse_flight_date("10 May 2023") is not None

    def test_the_flight_number_pattern_accepts_four_digits(self):
        assert re.fullmatch(_FLIGHT_NUM_BOUNDED, "SK 2601")
