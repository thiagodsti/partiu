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
Extract flight booking data from airline confirmation emails and return it as JSON.

YOUR RESPONSE MUST USE EXACTLY THIS STRUCTURE — no other field names are valid:

{"has_flight": true, "booking_reference": "ABC123", "flights": [
  {"flight_number": "SK117", "dep_airport": "ARN", "arr_airport": "CPH",
   "dep_datetime": "2025-06-10T06:15:00", "arr_datetime": null,
   "dep_date": "2025-06-10", "airline_name": "SAS", "airline_code": "SK",
   "passenger_name": "JANE SMITH", "seat": "14C", "cabin_class": "Economy"}
]}

If no flight booking: {"has_flight": false}

FIELD RULES:

has_flight: true only for confirmed bookings with a booking reference and flight \
numbers. false for marketing, loyalty updates, check-in reminders without itinerary.

flight_number: the identifier for a specific flight leg. \
Look for keywords "Voo", "Vuelo", "Flight", "Vol", "Flug", "Fly" followed by digits — \
those digits are the flight number. Also look for 3-5 digit numbers that appear \
alongside or immediately before/after a departure airport, arrival airport, or \
departure time — those are flight numbers. \
Always prefix with the airline's 2-letter IATA code: e.g. digits "4849" from an \
Azul email → "AD4849"; find the IATA code from the airline name or sender domain. \
If the code already has a 2-letter prefix (e.g. "SK117"), keep it as-is. \
Remove spaces: "LH 809" → "LH809". \
Booking references (short alphanumeric codes like "TQJWFX") are NOT flight numbers. \
Ticket numbers (long numeric strings, 10+ digits) are NOT flight numbers.

seat: the passenger's seat assignment — row number followed by a letter (e.g. "6C", \
"14A"). NEVER a plain number. null if not present.

dep_airport / arr_airport: exactly 3 uppercase IATA letters. Extract directly from \
the email — the code is always written explicitly. Look for patterns like \
"Frankfurt (FRA)", standalone "ARN", city then code "(FLN)", or "Partida de ARN". \
dep_airport and arr_airport must be different airports.

dep_datetime: format YYYY-MM-DDTHH:MM:SS — combine the date and time into one value. \
If the email shows "02/03 • 13:20", dep_datetime is "YYYY-03-02T13:20:00". \
arr_datetime: same format, or null. \
dep_date: format YYYY-MM-DD, or null. \
For any date shown as DD/MM without a year, derive the year from the "Email date" \
header — if the flight month is earlier than the email month, the year is +1.

airline_code: 2-letter IATA code only (e.g. SK, LH, LA, FR, AD). Never 3-letter.

passenger_name: copy exactly as written — never anonymize or replace with placeholders. \
If multiple passengers share the same booking, use the first passenger's name for every \
flight leg (repeat it on each leg — do not leave it null on any leg).

booking_reference: the PNR/confirmation code (short alphanumeric, e.g. TQJWFX). \
null if not present.

CONNECTING FLIGHTS: extract each leg as a separate flight object with its own \
flight_number, dep_airport, arr_airport, and times. The stop city is the arrival \
of leg 1 and the departure of leg 2.

Return only the JSON. No explanation, no markdown.
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


_FLIGHT_SCHEMA = {
    "type": "object",
    "required": ["has_flight"],
    "properties": {
        "has_flight": {"type": "boolean"},
        "booking_reference": {"type": ["string", "null"]},
        "flights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "flight_number": {"type": ["string", "null"]},
                    "dep_airport": {"type": ["string", "null"]},
                    "arr_airport": {"type": ["string", "null"]},
                    "dep_datetime": {"type": ["string", "null"]},
                    "arr_datetime": {"type": ["string", "null"]},
                    "dep_date": {"type": ["string", "null"]},
                    "airline_name": {"type": ["string", "null"]},
                    "airline_code": {"type": ["string", "null"]},
                    "passenger_name": {"type": ["string", "null"]},
                    "seat": {"type": ["string", "null"]},
                    "cabin_class": {"type": ["string", "null"]},
                },
            },
        },
    },
}


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
            "format": _FLIGHT_SCHEMA,
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

    # Fallback: look up the code from built-in rules when the LLM left it blank
    if not airline_code and airline_name and airline_name != "Unknown":
        from .parsers.builtin_rules import get_builtin_rules

        name_lower = airline_name.lower()
        for rule in get_builtin_rules():
            if rule.airline_code and (
                rule.airline_name.lower() in name_lower or name_lower in rule.airline_name.lower()
            ):
                airline_code = rule.airline_code
                break

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


# Lines that universally mark end-of-itinerary in airline emails — truncate here
_END_OF_CONTENT_RE = re.compile(
    r"^\s*(?:thank\s+you\s+for\s+your\s+(?:booking|purchase|order|reservation)"
    r"|best\s+regards|kind\s+regards|warm\s+regards|have\s+a\s+(?:pleasant|great|good|safe)\s+(?:journey|flight|trip)"
    r"|bon\s+voyage|boa\s+viagem|gute\s+reise"
    r"|corporate\s+headquarters|chairman\s+of\s+the\s+supervisory"
    r"|registration:\s+amtsgericht|executive\s+board:"
    # Post-itinerary service/marketing section headers
    r"|\w[\w\s]{2,30}online\s+services"  # e.g. "Lufthansa Online Services"
    r"|manage\s+(?:your\s+)?booking"
    r"|flight\s+services\s*$"  # standalone "Flight services" header
    r"|current\s+entry\s+regulations"
    r"|information\s+regarding\s+(?:medical|health|mask)"
    r"|baggage\s+services\s+via"
    r"|\w[\w\s]{2,20}on\s+your\s+mobile"  # e.g. "Lufthansa on your mobile"
    r"|print\s+your\s+online\s+boarding"
    r"|free\s+ejournals?"
    r"|easy\s+flight\s+data\s+transmission)\b",
    re.IGNORECASE,
)

# Individual noise lines to remove throughout the body (mid-email links, labels, legal)
_NOISE_LINE_RE = re.compile(
    r"^\s*(?:unsubscribe|terms\s+and\s+conditions|privacy\s+policy|legal\s+notice"
    r"|manage\s+(?:your\s+)?(?:email|preferences|subscription)"
    r"|you\s+(?:are\s+)?(?:receiving|subscribed)"
    r"|©|\u00a9|all\s+rights\s+reserved"
    r"|this\s+(?:email|message)\s+(?:was\s+sent|is\s+(?:auto|confirm))"
    r"|if\s+you\s+(?:no\s+longer|did\s+not|wish\s+to)"
    r"|co2\s+offset|sustainable\s+aviation\s+fuel"
    r"|imprint|impressum"
    r"|do\s+not\s+reply\s+to\s+this)\b",
    re.IGNORECASE,
)


def _remove_noise_lines(text: str) -> str:
    """
    Remove individual noise lines and truncate at clear end-of-itinerary markers.
    End-of-itinerary markers (e.g. 'Best regards', 'Thank you for your booking',
    corporate boilerplate) cut everything from that point — nothing useful follows.
    """
    result = []
    for line in text.splitlines():
        if _END_OF_CONTENT_RE.match(line):
            break
        if not _NOISE_LINE_RE.match(line):
            result.append(line)
    return "\n".join(result)


_PDF_CAP = 2000  # chars per PDF attachment sent to LLM


def build_llm_body(email_msg) -> str:
    """
    Build the body text to send to the LLM.

    Uses HTML (preferred) or plain text for the email body, strips noise,
    then appends PDF attachments capped at _PDF_CAP chars each and ICS data.
    This keeps PDFs from inflating the context with legal fine print.
    """
    import re as _re

    from .parsers.email_connector import _extract_text_from_pdf
    from .parsers.shared import html_to_text as _html_to_text

    def _clean(text: str) -> str:
        text = _re.sub(r"=\r?\n", "", text)
        text = _re.sub(r"=([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), text)
        text = text.replace("\xa0", " ").replace("\t", " ")
        text = _re.sub(r" {2,}", " ", text)
        return _remove_noise_lines(text)

    if email_msg.html_body:
        body_text = _clean(_html_to_text(email_msg.html_body))
    else:
        body_text = _clean(email_msg.body or "")

    for pdf_bytes in getattr(email_msg, "pdf_attachments", []):
        pdf_text = _extract_text_from_pdf(pdf_bytes)[:_PDF_CAP]
        if pdf_text:
            body_text = body_text + "\n\n--- PDF ATTACHMENT ---\n" + pdf_text

    if getattr(email_msg, "ics_texts", None):
        ics_block = "--- CALENDAR ATTACHMENTS ---\n" + "\n\n".join(email_msg.ics_texts)
        body_text = body_text + "\n\n" + ics_block

    return body_text


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

    body_text = build_llm_body(email_msg)

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
