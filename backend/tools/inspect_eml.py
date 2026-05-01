"""
Inspect .eml files through the exact same pipeline used in production.

Runs each email through: built-in rules → generic HTML → PDF → LLM fallback,
and shows which step found data and what would actually be stored.

Usage:
    uv run python -m backend.tools.inspect_eml ~/Downloads/brussels.eml
    uv run python -m backend.tools.inspect_eml ~/Downloads/*.eml
"""

from __future__ import annotations

import email as _email_lib
import email.utils as _eu
import glob
import sys
from pathlib import Path


def _section(title: str) -> None:
    width = 72
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print(f"{'=' * width}")


def _load_eml(path: Path):
    """Load an .eml file into an EmailMessage using the production connector."""
    from backend.parsers.email_connector import (
        EmailMessage,
        decode_header_value,
        get_email_body_and_html,
    )

    raw = path.read_bytes()
    msg = _email_lib.message_from_bytes(raw)

    sender = decode_header_value(msg.get("From", ""))
    subject = decode_header_value(msg.get("Subject", ""))
    message_id = msg.get("Message-ID", f"inspect-{path.stem}")

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


def _inspect(path: Path) -> None:
    from backend.llm_parser import llm_available, llm_extract_flights
    from backend.parsers.builtin_rules import get_builtin_rules
    from backend.parsers.engine import (
        extract_flights_from_email,
        match_rule_to_email,
        try_generic_html_extraction,
        try_generic_pdf_extraction,
    )

    _section(f"FILE: {path.name}")

    email_msg = _load_eml(path)
    print(f"  From    : {email_msg.sender}")
    print(f"  Subject : {email_msg.subject}")
    print(f"  Date    : {email_msg.date}")
    print(f"  Body    : {len(email_msg.body or '')} chars")
    if email_msg.ics_texts:
        print(f"  ICS     : {len(email_msg.ics_texts)} calendar attachment(s)")
    if email_msg.pdf_attachments:
        print(f"  PDF     : {len(email_msg.pdf_attachments)} attachment(s)")

    rules = get_builtin_rules()
    sorted_rules = sorted(rules, key=lambda r: (-r.priority, r.airline_name))

    flights_data = None
    step_name = None

    # Step 1: built-in rule match
    rule = match_rule_to_email(email_msg, sorted_rules)
    if rule:
        print(f"\n  [Step 1] Matched rule: {rule.airline_name}")
        flights_data = extract_flights_from_email(email_msg, rule)
        if flights_data:
            step_name = f"Rule: {rule.airline_name}"
        else:
            print("           Rule matched but extracted nothing — trying generic HTML fallback")
            flights_data = try_generic_html_extraction(email_msg, rule)
            if flights_data:
                step_name = f"Generic HTML (rule={rule.airline_name})"
    else:
        print("\n  [Step 1] No rule matched sender")

    # Step 2: generic HTML (no rule match)
    if not flights_data and not rule:
        print("  [Step 2] Trying generic HTML extraction...")
        flights_data = try_generic_html_extraction(email_msg)
        if flights_data:
            step_name = "Generic HTML"

    # Step 3: PDF fallback
    if not flights_data:
        print("  [Step 3] Trying generic PDF extraction...")
        flights_data = try_generic_pdf_extraction(email_msg)
        if flights_data:
            step_name = "PDF"

    # Step 4: LLM fallback
    if not flights_data:
        if llm_available():
            print("  [Step 4] Trying LLM fallback (Ollama)...")
            flights_data = llm_extract_flights(email_msg)
            if flights_data:
                step_name = "LLM (Ollama)"
        else:
            print("  [Step 4] LLM not configured (OLLAMA_URL not set) — skipping")

    _section("RESULT")

    if not flights_data:
        print("  No flights extracted — all steps returned nothing.")
        return

    print(f"  Extracted by : {step_name}")
    print(f"  Flights found: {len(flights_data)}")

    for i, f in enumerate(flights_data, 1):
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
        print("Usage: uv run python -m backend.tools.inspect_eml <file.eml> [file2.eml ...]")
        sys.exit(1)

    # Load .env so OLLAMA_URL etc. are available
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
        _inspect(path)

    print(f"\n{'=' * 72}\n  Done — inspected {len(paths)} file(s).\n{'=' * 72}\n")


if __name__ == "__main__":
    main()
