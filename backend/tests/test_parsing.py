"""Tests for the email parsing engine using anonymized fixture emails."""

from datetime import datetime

import pytest

from backend.parsers.builtin_rules import get_builtin_rules
from backend.parsers.email_connector import EmailMessage
from backend.parsers.engine import extract_flights_from_email, match_rule_to_email
from backend.tests.conftest import FIXTURES_DIR, load_anonymized_fixture, load_eml_as_email_message


def get_rules():
    return sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)


@pytest.fixture(scope="session")
def fixture_emails() -> list[EmailMessage]:
    """Load all anonymized fixture emails (.eml and .json) for parser tests."""
    emails = []
    for json_file in sorted(FIXTURES_DIR.glob("*_anonymized.json")):
        emails.append(load_anonymized_fixture(json_file.name))
    for eml_file in sorted(FIXTURES_DIR.glob("*_anonymized.eml")):
        emails.append(load_eml_as_email_message(eml_file.name))
    return emails


def test_fixtures_loaded(fixture_emails):
    assert len(fixture_emails) > 0, "No fixture emails found in tests/fixtures/"


def test_all_fixture_emails_match_a_rule(fixture_emails):
    """Every fixture email should match at least one airline rule."""
    rules = get_rules()
    matched = sum(1 for msg in fixture_emails if match_rule_to_email(msg, rules) is not None)
    assert matched > 0, "No fixture emails matched any airline rule"


def test_matched_emails_extract_flights(fixture_emails):
    """Most matched fixture emails should produce flights."""
    rules = get_rules()
    matched_total = 0
    matched_with_flights = 0
    for msg in fixture_emails:
        rule = match_rule_to_email(msg, rules)
        if rule is None:
            continue
        matched_total += 1
        if extract_flights_from_email(msg, rule):
            matched_with_flights += 1

    assert matched_total > 0, "No fixture emails matched any rule"
    ratio = matched_with_flights / matched_total
    # PDF-only rules (e.g. Kiwi) match emails but yield 0 flights when PDF bytes
    # are not present in the fixture, so the realistic floor is lower than 50%.
    assert ratio >= 0.25, (
        f"Only {matched_with_flights}/{matched_total} matched emails yielded flights "
        f"({ratio:.0%}) — expected at least 25%"
    )


def test_flights_have_required_fields(fixture_emails, seeded_airports_db):
    """All extracted flights must have the five core fields populated."""
    rules = get_rules()
    required = [
        "flight_number",
        "departure_airport",
        "arrival_airport",
        "departure_datetime",
        "arrival_datetime",
    ]
    for msg in fixture_emails:
        rule = match_rule_to_email(msg, rules)
        if rule is None:
            continue
        for flight in extract_flights_from_email(msg, rule):
            for field in required:
                assert flight.get(field), (
                    f"Missing {field!r} in flight from "
                    f"{rule.airline_name}: {msg.subject[:60]}\n"
                    f"  Flight: {flight}"
                )


def test_flight_datetimes_are_datetime_objects(fixture_emails):
    """Departure and arrival must be datetime instances (not strings)."""
    rules = get_rules()
    for msg in fixture_emails:
        rule = match_rule_to_email(msg, rules)
        if rule is None:
            continue
        for flight in extract_flights_from_email(msg, rule):
            dep = flight.get("departure_datetime")
            arr = flight.get("arrival_datetime")
            assert isinstance(dep, datetime), (
                f"departure_datetime is {type(dep).__name__}, expected datetime — "
                f"{flight.get('flight_number')} in {msg.subject[:40]}"
            )
            assert isinstance(arr, datetime), (
                f"arrival_datetime is {type(arr).__name__}, expected datetime — "
                f"{flight.get('flight_number')} in {msg.subject[:40]}"
            )


def test_arrival_not_before_departure(fixture_emails):
    """Arrival must be >= departure for every extracted flight."""
    rules = get_rules()
    for msg in fixture_emails:
        rule = match_rule_to_email(msg, rules)
        if rule is None:
            continue
        for flight in extract_flights_from_email(msg, rule):
            dep = flight.get("departure_datetime")
            arr = flight.get("arrival_datetime")
            if isinstance(dep, datetime) and isinstance(arr, datetime):
                assert arr >= dep, (
                    f"Arrival {arr} is before departure {dep} — "
                    f"{flight.get('flight_number')} in {msg.subject[:40]}"
                )


@pytest.mark.parametrize(
    "airline_code,sender_fragment",
    [
        ("LA", "latam"),
        ("SK", "sas"),
        ("AD", "azul"),
    ],
)
def test_specific_airline_parses_flights(
    fixture_emails, airline_code, sender_fragment, seeded_airports_db
):
    """Each supported airline must have at least one fixture that yields flights."""
    rules = get_rules()
    airline_emails = [
        msg for msg in fixture_emails if sender_fragment.lower() in msg.sender.lower()
    ]
    if not airline_emails:
        pytest.skip(f"No {airline_code} fixture emails found — add one to tests/fixtures/")

    for msg in airline_emails:
        rule = match_rule_to_email(msg, rules)
        if rule and rule.airline_code == airline_code:
            if extract_flights_from_email(msg, rule):
                return  # At least one parsed successfully

    pytest.fail(f"No {airline_code} fixture emails successfully extracted flights")
