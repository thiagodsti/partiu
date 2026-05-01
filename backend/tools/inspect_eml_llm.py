"""
Inspect .eml files through the LLM parser only (skips built-in rules).

Shows the raw model response, per-flight validation results, and the final
normalised output — so you can debug exactly what the model returned and
why any flight was rejected.

Uses the exact same production functions: _call_ollama, _validate_flight,
_normalise_flight from llm_parser.py.

Usage:
    uv run python -m backend.tools.inspect_eml_llm ~/Downloads/brussels.eml
    uv run python -m backend.tools.inspect_eml_llm ~/Downloads/*.eml
"""

from __future__ import annotations

import email as _email_lib
import email.utils as _eu
import glob
import json
import sys
from datetime import UTC, datetime
from pathlib import Path


def _section(title: str) -> None:
    width = 72
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print(f"{'=' * width}")


def _load_eml(path: Path):
    from backend.parsers.email_connector import (
        EmailMessage,
        decode_header_value,
        get_email_body_and_html,
    )

    raw = path.read_bytes()
    msg = _email_lib.message_from_bytes(raw)

    sender = decode_header_value(msg.get("From", ""))
    subject = decode_header_value(msg.get("Subject", ""))
    message_id = msg.get("Message-ID", f"inspect-llm-{path.stem}")

    body, raw_html, pdf_bytes_list, ics_texts = get_email_body_and_html(msg)

    msg_date = None
    date_str = msg.get("Date", "")
    if date_str:
        try:
            msg_date = _eu.parsedate_to_datetime(date_str)
        except Exception:
            pass

    return EmailMessage(
        message_id=message_id,
        sender=sender,
        subject=subject,
        body=body,
        date=msg_date,
        html_body=raw_html,
        pdf_attachments=pdf_bytes_list,
        raw_eml=raw,
        ics_texts=ics_texts,
    )


def _explain_validation_failure(f: dict) -> list[str]:
    """Return human-readable reasons why a flight dict fails _validate_flight."""
    import re

    iata_re = re.compile(r"^[A-Z]{3}$")
    fn_re = re.compile(r"^[A-Z]{2}\d{1,4}[A-Z]?$")

    dep = (f.get("dep_airport") or "").upper()
    arr = (f.get("arr_airport") or "").upper()
    fn = (f.get("flight_number") or "").upper().replace(" ", "").replace("\xa0", "")

    reasons = []
    if not fn:
        reasons.append("flight_number is missing")
    elif not fn_re.match(fn):
        reasons.append(f"flight_number '{fn}' does not match [A-Z]{{2}}\\d{{1,4}} pattern")
    if not dep:
        reasons.append("dep_airport is missing")
    elif not iata_re.match(dep):
        reasons.append(f"dep_airport '{dep}' is not a valid 3-letter IATA code")
    if not arr:
        reasons.append("arr_airport is missing")
    elif not iata_re.match(arr):
        reasons.append(f"arr_airport '{arr}' is not a valid 3-letter IATA code")
    if dep and arr and dep == arr:
        reasons.append(f"dep_airport == arr_airport ('{dep}') — model confused the airports")
    if not f.get("dep_datetime") and not f.get("dep_date"):
        reasons.append("no dep_datetime or dep_date")
    return reasons


def _dump_html_structure(html: str) -> None:
    """Print all HTML tags that have a class or id, with first line of their text."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    for tag in soup.find_all(True):
        cls = tag.get("class")
        tid = tag.get("id")
        if not cls and not tid:
            continue
        cls_str = " ".join(cls) if isinstance(cls, list) else (cls or "")
        id_str = tid or ""
        key = f"{tag.name}.{cls_str}#{id_str}"
        if key in seen:
            continue
        seen.add(key)
        first_line = (tag.get_text(separator=" ", strip=True) or "")[:80].replace("\n", " ")
        print(f"  <{tag.name} class={cls_str!r} id={id_str!r}>  →  {first_line!r}")


def _inspect(path: Path, dump_body: bool = False, dump_html: bool = False) -> None:
    from backend.config import settings
    from backend.llm_parser import (
        _PROMPT_USER_TEMPLATE,
        _call_ollama,
        _normalise_flight,
        build_llm_body,
    )

    _section(f"FILE: {path.name}")

    if not settings.OLLAMA_URL:
        print("  ERROR: OLLAMA_URL is not set — LLM parser is disabled.")
        print("  Set OLLAMA_URL and OLLAMA_MODEL in your .env file.")
        return

    email_msg = _load_eml(path)
    print(f"  From    : {email_msg.sender}")
    print(f"  Subject : {email_msg.subject}")
    print(f"  Date    : {email_msg.date}")
    print(f"  Body    : {len(email_msg.body or '')} chars")

    if dump_html and email_msg.html_body:
        _section("HTML STRUCTURE (tags with class/id)")
        _dump_html_structure(email_msg.html_body)
        _section("END OF HTML STRUCTURE")
    if email_msg.ics_texts:
        print(f"  ICS     : {len(email_msg.ics_texts)} calendar attachment(s)")
    if email_msg.pdf_attachments:
        print(f"  PDF     : {len(email_msg.pdf_attachments)} attachment(s)")

    # Build body exactly as production does
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    body_text = build_llm_body(email_msg)

    prompt = _PROMPT_USER_TEMPLATE.format(
        today=today,
        sender=email_msg.sender or "",
        subject=email_msg.subject or "",
        body=body_text,
    )

    if dump_body:
        _section("BODY SENT TO MODEL")
        print(body_text)
        _section("END OF BODY")

    print(f"\n  Sending to Ollama ({settings.OLLAMA_MODEL}) — please wait...")
    print(f"  Body sent to model: {len(body_text)} chars")

    raw = _call_ollama(
        prompt, settings.OLLAMA_MODEL, settings.OLLAMA_URL, timeout=settings.OLLAMA_TIMEOUT
    )

    _section("RAW MODEL RESPONSE")
    if not raw:
        print("  ERROR: Ollama returned nothing (connection error or timeout).")
        return
    print(raw)

    _section("PARSED RESULT")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("  ERROR: model did not return valid JSON — see raw response above.")
        return

    if not data.get("has_flight"):
        print(f"  Model says NO FLIGHT — has_flight={data.get('has_flight')!r}")
        return

    raw_flights = data.get("flights") or []
    booking_ref = data.get("booking_reference") or ""
    print("  has_flight     : True")
    print(f"  booking_ref    : {booking_ref or '(none)'}")
    print(f"  flights in JSON: {len(raw_flights)}")

    valid_flights = []
    for i, f in enumerate(raw_flights, 1):
        if not isinstance(f, dict):
            print(f"\n  Flight {i}: not a dict — skipped")
            continue
        if not f.get("booking_reference") and booking_ref:
            f["booking_reference"] = booking_ref

        reasons = _explain_validation_failure(f)
        if reasons:
            print(f"\n  Flight {i}: FAILED VALIDATION")
            for r in reasons:
                print(f"    ✗ {r}")
            print(f"    Raw: {f}")
        else:
            print(f"\n  Flight {i}: passed validation")
            valid_flights.append(_normalise_flight(f, "", ""))

    _section("NORMALISED OUTPUT (what would be stored)")
    if not valid_flights:
        print("  No flights passed validation — nothing would be stored.")
        return

    print(f"  Flights: {len(valid_flights)}")
    for i, f in enumerate(valid_flights, 1):
        print(f"\n  --- Flight {i} ---")
        print(f"    Flight #   : {f.get('flight_number')}")
        print(f"    Airline    : {f.get('airline_name')} ({f.get('airline_code')})")
        print(f"    Route      : {f.get('departure_airport')} → {f.get('arrival_airport')}")
        print(f"    Departure  : {f.get('departure_datetime')}")
        print(f"    Arrival    : {f.get('arrival_datetime')}")
        print(f"    Booking ref: {f.get('booking_reference') or '(none)'}")
        print(f"    Passenger  : {f.get('passenger_name') or '(none)'}")
        print(f"    Seat       : {f.get('seat') or '(none)'}")
        print(f"    Cabin      : {f.get('cabin_class') or '(none)'}")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(
            "Usage: uv run python -m backend.tools.inspect_eml_llm <file.eml> [file2.eml ...] [--dump-body] [--dump-html]"
        )
        sys.exit(1)

    dump_body = "--dump-body" in args
    dump_html = "--dump-html" in args
    args = [a for a in args if a not in ("--dump-body", "--dump-html")]

    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).parent.parent.parent / ".env")
    except ImportError:
        pass

    paths: list[Path] = []
    for arg in args:
        expanded = glob.glob(arg)
        if expanded:
            paths.extend(Path(p) for p in sorted(expanded))
        else:
            paths.append(Path(arg))

    for path in paths:
        if not path.exists():
            print(f"[SKIP] File not found: {path}")
            continue
        _inspect(path, dump_body=dump_body, dump_html=dump_html)

    print(f"\n{'=' * 72}\n  Done — inspected {len(paths)} file(s).\n{'=' * 72}\n")


if __name__ == "__main__":
    main()
