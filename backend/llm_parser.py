"""
LLM-based flight extractor — optional fallback for unknown airlines.

Calls a locally running Ollama instance and asks it to extract structured
flight data from raw email text.  Completely disabled when OLLAMA_URL is
not set in the environment.

Usage (programmatic):
    from backend.llm_parser import llm_extract_flights, llm_available
    if llm_available():
        flights = llm_extract_flights(email_msg)
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_PROMPT_SYSTEM = """\
You are a flight data extraction assistant. Your only job is to extract \
structured flight booking information from airline confirmation emails.

Rules:
- Extract ONLY flights that have a real booking confirmation (ticket issued, \
  booking reference present, or clear itinerary with flight numbers).
- Do NOT extract flights from marketing emails, loyalty programme updates, \
  "time to check in" reminders with no booking data, or promotional offers.
- Return a JSON object. Nothing else — no explanation, no markdown fences.
- If the email contains valid flight bookings return:
  {"has_flight": true, "booking_reference": "...", "flights": [...]}
- If the email does NOT contain a valid flight booking return:
  {"has_flight": false}

Each flight object must have these exact keys (use null if unknown):
  flight_number   – e.g. "LA3045" (IATA airline code + digits, no spaces)
  dep_airport     – 3-letter IATA code, e.g. "GRU"
  arr_airport     – 3-letter IATA code, e.g. "LIS"
  dep_datetime    – ISO 8601 local time, e.g. "2026-04-10T23:15:00"
  arr_datetime    – ISO 8601 local time, e.g. "2026-04-11T13:30:00"
  dep_date        – "YYYY-MM-DD" (used when full datetime is not available)
  airline_name    – full airline name, e.g. "LATAM Airlines"
  airline_code    – 2-letter IATA code, e.g. "LA"
  passenger_name  – full name if present, else null
  seat            – seat number if present, else null
  cabin_class     – e.g. "Economy", "Business", else null
"""

_PROMPT_USER_TEMPLATE = """\
Extract flight data from the following email.

Sender: {sender}
Subject: {subject}

Email body (first 4000 chars):
{body}
"""

_IATA_RE = re.compile(r"^[A-Z]{3}$")
# Allow: LA3045, FR2878, G3-2108, G32108 (IATA or ICAO airline code + optional dash + digits)
_FN_RE = re.compile(r"^[A-Z][A-Z0-9]-?\d{3,5}$")


def llm_available() -> bool:
    """Return True if Ollama is configured (OLLAMA_URL is set)."""
    from .config import settings

    return bool(settings.OLLAMA_URL)


def _call_ollama(prompt: str, model: str, ollama_url: str) -> str | None:
    """Send a chat completion request to Ollama and return the raw response text."""
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": _PROMPT_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {"temperature": 0},
            "format": "json",
        }
    ).encode()

    url = ollama_url.rstrip("/") + "/api/chat"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data.get("message", {}).get("content", "")
    except urllib.error.URLError as e:
        logger.warning("Ollama request failed: %s", e)
        return None
    except Exception as e:
        logger.warning("Ollama unexpected error: %s", e)
        return None


def _validate_flight(flight: dict[str, Any]) -> bool:
    """Basic sanity checks so we don't insert obviously wrong data."""
    dep = (flight.get("dep_airport") or "").upper()
    arr = (flight.get("arr_airport") or "").upper()
    fn = (flight.get("flight_number") or "").upper().replace(" ", "").replace("\xa0", "")
    if not _IATA_RE.match(dep) or not _IATA_RE.match(arr):
        return False
    if dep == arr:
        return False
    if fn and not _FN_RE.match(fn):
        return False
    # Must have at least a dep_date or dep_datetime
    if not flight.get("dep_datetime") and not flight.get("dep_date"):
        return False
    return True


def _normalise_flight(flight: dict[str, Any], rule_name: str, rule_code: str) -> dict[str, Any]:
    """Normalise LLM output into the schema expected by insert_flight."""
    from datetime import UTC, datetime

    dep_airport = (flight.get("dep_airport") or "").upper()
    arr_airport = (flight.get("arr_airport") or "").upper()
    fn = (
        (flight.get("flight_number") or "")
        .upper()
        .replace(" ", "")
        .replace("\xa0", "")
        .replace("-", "")
    )

    # Parse departure datetime
    dep_dt = None
    dep_raw = flight.get("dep_datetime") or flight.get("dep_date") or ""
    if dep_raw:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                dep_dt = datetime.strptime(dep_raw[:19], fmt).replace(tzinfo=UTC)
                break
            except ValueError:
                continue

    arr_dt = None
    arr_raw = flight.get("arr_datetime") or ""
    if arr_raw:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                arr_dt = datetime.strptime(arr_raw[:19], fmt).replace(tzinfo=UTC)
                break
            except ValueError:
                continue

    airline_name = flight.get("airline_name") or rule_name or "Unknown"
    airline_code = (flight.get("airline_code") or rule_code or "").upper()

    return {
        "flight_number": fn,
        "departure_airport": dep_airport,
        "arrival_airport": arr_airport,
        "departure_datetime": dep_dt,
        "arrival_datetime": arr_dt,
        "booking_reference": flight.get("booking_reference") or "",
        "passenger_name": flight.get("passenger_name") or "",
        "seat": flight.get("seat") or "",
        "cabin_class": flight.get("cabin_class") or "",
        "airline_name": airline_name,
        "airline_code": airline_code,
        "departure_terminal": "",
        "arrival_terminal": "",
        "departure_gate": "",
        "arrival_gate": "",
    }


def llm_extract_flights(email_msg, timeout: int = 60) -> list[dict]:
    """
    Ask the configured Ollama model to extract flights from an email.

    Returns a list of normalised flight dicts (same schema as rule-based
    parsers), or an empty list if:
      - Ollama is not configured
      - The model says there are no flights
      - The output fails validation
    """
    from .config import settings

    if not settings.OLLAMA_URL:
        return []

    body_text = (email_msg.body or "")[:4000]
    prompt = _PROMPT_USER_TEMPLATE.format(
        sender=email_msg.sender or "",
        subject=email_msg.subject or "",
        body=body_text,
    )

    raw = _call_ollama(prompt, settings.OLLAMA_MODEL, settings.OLLAMA_URL)
    if not raw:
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.debug("LLM returned non-JSON: %s", raw[:200])
        return []

    if not data.get("has_flight"):
        return []

    raw_flights = data.get("flights") or []
    booking_ref = data.get("booking_reference") or ""

    results = []
    for f in raw_flights:
        if not isinstance(f, dict):
            continue
        # Backfill booking_reference from top-level if missing
        if not f.get("booking_reference") and booking_ref:
            f["booking_reference"] = booking_ref
        if not _validate_flight(f):
            logger.debug("LLM flight failed validation: %s", f)
            continue
        results.append(_normalise_flight(f, "", ""))

    return results
