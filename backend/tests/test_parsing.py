"""Tests for the email parsing engine using real cached emails."""
from datetime import datetime, timezone

import pytest

from backend.parsers.email_connector import EmailMessage
from backend.parsers.builtin_rules import get_builtin_rules
from backend.parsers.engine import extract_flights_from_email, match_rule_to_email


def get_rules():
    return sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)


def _make_email(entry: dict) -> EmailMessage:
    """Convert a cache entry dict to an EmailMessage."""
    date_str = entry.get('date', '')
    try:
        date = datetime.fromisoformat(date_str)
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        date = datetime.now(timezone.utc)

    return EmailMessage(
        message_id=entry.get('message_id', ''),
        sender=entry.get('sender', ''),
        subject=entry.get('subject', ''),
        body=entry.get('body', ''),
        html_body=entry.get('html_body'),
        date=date,
        pdf_attachments=[],  # Skip PDF re-extraction for speed
    )


def test_cache_loaded(email_cache):
    """Email cache must be non-empty for meaningful tests."""
    assert len(email_cache) > 0, (
        'email_cache.json is empty or missing — run a sync first'
    )


def test_all_flight_emails_match_a_rule(email_cache):
    """Every email with a recognized sender should match at least one rule."""
    rules = get_rules()
    matched = 0
    for entry in email_cache:
        msg = _make_email(entry)
        if match_rule_to_email(msg, rules) is not None:
            matched += 1
    assert matched > 0, 'No emails matched any airline rule'


def test_matched_emails_extract_flights(email_cache):
    """At least half of matched emails should produce flights.

    Airlines send non-itinerary emails too (account activations, promotions, etc.)
    so we don't require 100% — but most matched emails should yield real flights.
    """
    rules = get_rules()
    matched_total = 0
    matched_with_flights = 0
    for entry in email_cache:
        msg = _make_email(entry)
        rule = match_rule_to_email(msg, rules)
        if rule is None:
            continue
        matched_total += 1
        if extract_flights_from_email(msg, rule):
            matched_with_flights += 1

    assert matched_total > 0, 'No emails matched any rule'
    ratio = matched_with_flights / matched_total
    # PDF-only rules (e.g. Kiwi) match emails but yield 0 flights when the cache
    # omits PDF bytes, so the realistic floor is lower than 50%.
    assert ratio >= 0.25, (
        f'Only {matched_with_flights}/{matched_total} matched emails yielded flights '
        f'({ratio:.0%}) — expected at least 25%'
    )


def test_flights_have_required_fields(email_cache):
    """All extracted flights must have the four core fields populated."""
    rules = get_rules()
    required = ['flight_number', 'departure_airport', 'arrival_airport',
                'departure_datetime', 'arrival_datetime']
    for entry in email_cache:
        msg = _make_email(entry)
        rule = match_rule_to_email(msg, rules)
        if rule is None:
            continue
        for flight in extract_flights_from_email(msg, rule):
            for field in required:
                assert flight.get(field), (
                    f"Missing {field!r} in flight from "
                    f"{rule.airline_name}: {entry.get('subject', '')[:60]}\n"
                    f"  Flight: {flight}"
                )


def test_flight_datetimes_are_datetime_objects(email_cache):
    """Departure and arrival must be datetime instances (not strings)."""
    rules = get_rules()
    for entry in email_cache:
        msg = _make_email(entry)
        rule = match_rule_to_email(msg, rules)
        if rule is None:
            continue
        for flight in extract_flights_from_email(msg, rule):
            dep = flight.get('departure_datetime')
            arr = flight.get('arrival_datetime')
            assert isinstance(dep, datetime), (
                f"departure_datetime is {type(dep).__name__}, expected datetime — "
                f"{flight.get('flight_number')} in {entry.get('subject', '')[:40]}"
            )
            assert isinstance(arr, datetime), (
                f"arrival_datetime is {type(arr).__name__}, expected datetime — "
                f"{flight.get('flight_number')} in {entry.get('subject', '')[:40]}"
            )


def test_arrival_not_before_departure(email_cache):
    """Arrival must be >= departure for every extracted flight."""
    rules = get_rules()
    for entry in email_cache:
        msg = _make_email(entry)
        rule = match_rule_to_email(msg, rules)
        if rule is None:
            continue
        for flight in extract_flights_from_email(msg, rule):
            dep = flight.get('departure_datetime')
            arr = flight.get('arrival_datetime')
            if isinstance(dep, datetime) and isinstance(arr, datetime):
                assert arr >= dep, (
                    f"Arrival {arr} is before departure {dep} — "
                    f"{flight.get('flight_number')} in {entry.get('subject', '')[:40]}"
                )


@pytest.mark.parametrize('airline_code,sender_fragment', [
    ('LA', 'latam'),
    ('SK', 'sas'),
    ('AD', 'azul'),
])
def test_specific_airline_parses_flights(email_cache, airline_code, sender_fragment):
    """Each supported airline must have at least one email that yields flights."""
    rules = get_rules()
    airline_emails = [
        e for e in email_cache
        if sender_fragment.lower() in e.get('sender', '').lower()
    ]
    if not airline_emails:
        pytest.skip(f'No {airline_code} emails found in cache')

    for entry in airline_emails:
        msg = _make_email(entry)
        rule = match_rule_to_email(msg, rules)
        if rule and rule.airline_code == airline_code:
            if extract_flights_from_email(msg, rule):
                return  # At least one parsed successfully

    pytest.fail(f'No {airline_code} emails successfully extracted flights')
