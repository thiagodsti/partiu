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
You are a flight data extraction assistant. Extract structured flight booking \
information from airline confirmation emails.

RULES:
- Extract ONLY confirmed bookings: ticket issued, booking reference present, \
  clear itinerary with flight numbers and dates.
- Do NOT extract from: marketing emails, loyalty updates, seat upgrade offers, \
  check-in reminders that contain no itinerary, or promotional emails.
- Return ONLY a JSON object. No explanation, no markdown, no extra text.
- Use ONLY data that explicitly appears in the email. Never invent or guess \
  airport codes, dates, or flight numbers. If a value is not in the email, \
  use null.

DATES:
- Dates MUST be taken from the email content. NEVER use today's date.
- If no date is clearly written in the email, use null — do not guess.
- dep_datetime and arr_datetime format: "YYYY-MM-DDTHH:MM:SS" (e.g. "2025-06-10T23:15:00").
- dep_date format: "YYYY-MM-DD" (e.g. "2025-06-10").

AIRPORT CODES:
- dep_airport and arr_airport MUST be exactly 3 uppercase IATA letters (e.g. GRU, LIS, CDG, ARN, CPT).
- IATA airport codes are always 3 letters. City names, addresses, and country names are NOT airport codes.
- If you cannot find the 3-letter IATA code in the email, use null — never use a city name or address.
- Common codes: Stockholm=ARN, Lisbon=LIS, London Heathrow=LHR, Paris CDG=CDG, Frankfurt=FRA, \
  São Paulo Guarulhos=GRU, Oslo=OSL, Copenhagen=CPH, Helsinki=HEL, Cape Town=CPT, \
  Johannesburg=JNB, Rome=FCO, Milan Linate=LIN, Milan Malpensa=MXP.

FLIGHT NUMBERS:
- Flight numbers are assigned by airlines and look like: SK1462, LA3045, FR2878, LH803, BA436.
- Format: 2-letter airline IATA code + 3-5 digits, no spaces (e.g. SK117, LH271, TP523).
- Booking references (e.g. KI4K6A, Y52PHH, ABC123) are NOT flight numbers — put them in booking_reference.
- Ticket numbers (long numeric strings like 117-2539936905) are NOT flight numbers — use null.
- If you cannot find a proper flight number, use null.

AIRLINE CODES:
- airline_code MUST be the 2-letter IATA code (e.g. SK for SAS, LA for LATAM, LH for Lufthansa, \
  BA for British Airways, TP for TAP, FR for Ryanair, DY for Norwegian, AY for Finnair).
- Never use 3-letter codes (e.g. "SAS", "TAP") — always use the 2-letter IATA code.

OUTPUT FORMAT — with flights:
{"has_flight": true, "booking_reference": "ABC123", "flights": [<flight>, ...]}

OUTPUT FORMAT — no valid booking:
{"has_flight": false}

Each flight object:
{
  "flight_number":  "SK117",
  "dep_airport":    "ARN",
  "arr_airport":    "LIS",
  "dep_datetime":   "2025-06-10T23:15:00",
  "arr_datetime":   "2025-06-11T05:30:00",
  "dep_date":       "2025-06-10",
  "airline_name":   "SAS",
  "airline_code":   "SK",
  "passenger_name": "JOHN DOE",
  "seat":           "12A",
  "cabin_class":    "Economy"
}

EXAMPLE — SAS two-leg booking:
Email says: "Booking ref Y52PHH. SK117 ARN→CPH 10Jun2025 06:15, SK563 CPH→LIS 10Jun2025 09:00. Passenger: JOHN DOE"
Output:
{"has_flight": true, "booking_reference": "Y52PHH", "flights": [
  {"flight_number": "SK117", "dep_airport": "ARN", "arr_airport": "CPH",
   "dep_datetime": "2025-06-10T06:15:00", "arr_datetime": null,
   "dep_date": "2025-06-10", "airline_name": "SAS", "airline_code": "SK",
   "passenger_name": "JOHN DOE", "seat": null, "cabin_class": null},
  {"flight_number": "SK563", "dep_airport": "CPH", "arr_airport": "LIS",
   "dep_datetime": "2025-06-10T09:00:00", "arr_datetime": null,
   "dep_date": "2025-06-10", "airline_name": "SAS", "airline_code": "SK",
   "passenger_name": "JOHN DOE", "seat": null, "cabin_class": null}
]}

EXAMPLE — not a booking:
Email says: "Earn double miles this weekend on all SAS flights!"
Output:
{"has_flight": false}

EXAMPLE — check-in reminder with no itinerary:
Email says: "It's time to check in for your flight tomorrow!"
Output:
{"has_flight": false}
"""

_PROMPT_USER_TEMPLATE = """\
Extract flight data from the following email. Use ONLY dates and codes that appear in the email body.

Sender: {sender}
Subject: {subject}
Email date: {today}

Email body:
{body}
"""

_IATA_RE = re.compile(r"^[A-Z]{3}$")
from .utils import FLIGHT_NUMBER_RE as _FN_RE  # noqa: E402


def llm_available() -> bool:
    """Return True if Ollama is configured (OLLAMA_URL is set)."""
    from .config import settings

    return bool(settings.OLLAMA_URL)


def _call_ollama(prompt: str, model: str, ollama_url: str, timeout: int = 180) -> str | None:
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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
    # All three are required
    if not dep or not arr or not fn:
        return False
    if not _IATA_RE.match(dep) or not _IATA_RE.match(arr):
        return False
    if dep == arr:
        return False
    if not _FN_RE.match(fn):
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

    from datetime import UTC, datetime

    today = datetime.now(UTC).strftime("%Y-%m-%d")

    # Prefer plain-text body; fall back to stripped HTML
    body_text = email_msg.body or ""
    if not body_text and email_msg.html_body:
        from bs4 import BeautifulSoup

        body_text = BeautifulSoup(email_msg.html_body, "lxml").get_text(separator="\n")
    body_text = body_text[:4000]

    prompt = _PROMPT_USER_TEMPLATE.format(
        today=today,
        sender=email_msg.sender or "",
        subject=email_msg.subject or "",
        body=body_text,
    )

    raw = _call_ollama(
        prompt, settings.OLLAMA_MODEL, settings.OLLAMA_URL, timeout=settings.OLLAMA_TIMEOUT
    )
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
