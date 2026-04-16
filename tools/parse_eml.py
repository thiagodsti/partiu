#!/usr/bin/env python3
"""
Debug tool: parse a .eml file and print which rule matched + extracted flights.

Usage:
    python tools/parse_eml.py path/to/email.eml
    python tools/parse_eml.py path/to/email.eml --generate-test
    python tools/parse_eml.py path/to/email.eml --generate-test --out backend/tests/test_myairline.py

Options:
    --generate-test     Scaffold a ready-to-run pytest test file from the output.
    --out FILE          Where to write the generated test (default: stdout).
"""

import argparse
import email as stdlib_email
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# Make sure the project root is on sys.path so backend is importable.
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_eml(path: Path):
    """Parse a .eml file into a backend EmailMessage."""
    from backend.parsers.email_connector import EmailMessage, decode_header_value

    raw = path.read_bytes()
    msg = stdlib_email.message_from_bytes(raw)

    body = ""
    html_body = ""
    pdf_attachments = []

    for part in msg.walk():
        ct = part.get_content_type()
        if ct == "text/plain" and not body:
            body = part.get_payload(decode=True).decode("utf-8", errors="replace")
        elif ct == "text/html" and not html_body:
            html_body = part.get_payload(decode=True).decode("utf-8", errors="replace")
        elif ct == "application/pdf":
            pdf_attachments.append(part.get_payload(decode=True))

    return EmailMessage(
        message_id=f"debug-{path.name}",
        sender=decode_header_value(msg.get("From") or ""),
        subject=decode_header_value(msg.get("Subject") or ""),
        body=body,
        date=datetime.now(tz=UTC),
        html_body=html_body,
        pdf_attachments=pdf_attachments,
    )


def _serialize_flight(f: dict) -> dict:
    """Return a JSON-serializable copy of a flight dict."""
    out = {}
    for k, v in f.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(eml_path: Path):
    from backend.parsers.builtin_rules import get_builtin_rules
    from backend.parsers.engine import extract_flights_from_email, match_rule_to_email

    print(f"\n{'=' * 60}")
    print(f"  File   : {eml_path}")
    print(f"{'=' * 60}\n")

    email_msg = _load_eml(eml_path)

    print(f"  From   : {email_msg.sender}")
    print(f"  Subject: {email_msg.subject}")
    print(f"  Has HTML  : {'yes' if email_msg.html_body else 'no'}")
    print(f"  PDFs      : {len(email_msg.pdf_attachments)}")
    print()

    rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)
    rule = match_rule_to_email(email_msg, rules)

    if rule is None:
        print("  ❌  No rule matched.\n")
        print("  → Trying generic HTML / PDF fallback (no airline rule required) …\n")

        from backend.parsers.engine import try_generic_html_extraction, try_generic_pdf_extraction

        flights = try_generic_html_extraction(email_msg)
        if not flights:
            flights = try_generic_pdf_extraction(email_msg)

        if not flights:
            print("  ❌  Generic fallback also returned 0 flights.\n")
            print("  → Next steps:")
            print("    1. Add a rule to backend/parsers/builtin_rules.py")
            print("    2. Add an extractor in backend/parsers/airlines/")
            print("    3. Register it in backend/parsers/airlines/__init__.py\n")
            return None, []

        print(f"  ⚠️  Generic fallback extracted {len(flights)} flight(s) (no rule):\n")
        for i, f in enumerate(flights):
            print(
                f"  [{i}] {f.get('flight_number', '?'):8}  "
                f"{f.get('departure_airport', '?')} → {f.get('arrival_airport', '?')}  "
                f"{str(f.get('departure_datetime', '?'))[:16]}  "
                f"{f.get('airline_name', '?')}"
            )
        print()
        print("  Full output (JSON):")
        print(
            "  "
            + json.dumps([_serialize_flight(f) for f in flights], indent=2).replace("\n", "\n  ")
        )
        print()
        print("  → To get a proper parser, add a rule to backend/parsers/builtin_rules.py")
        print("    and an extractor in backend/parsers/airlines/\n")
        return None, flights

    print(f"  ✅  Rule matched: {rule.airline_name!r} (extractor: {rule.custom_extractor!r})\n")

    flights = extract_flights_from_email(email_msg, rule)

    if not flights:
        print("  ⚠️  Rule matched but 0 flights extracted.\n")
        print("  → The extractor ran but returned nothing.")
        print("    Check backend/parsers/airlines/<extractor>.py\n")
        return rule, []

    print(f"  ✅  {len(flights)} flight(s) extracted:\n")
    for i, f in enumerate(flights):
        print(
            f"  [{i}] {f.get('flight_number', '?'):8}  "
            f"{f.get('departure_airport', '?')} → {f.get('arrival_airport', '?')}  "
            f"{str(f.get('departure_datetime', '?'))[:16]}  "
            f"{f.get('airline_name', '?')}"
        )

    print()
    print("  Full output (JSON):")
    print(
        "  " + json.dumps([_serialize_flight(f) for f in flights], indent=2).replace("\n", "\n  ")
    )
    print()

    return rule, flights


def generate_test(eml_path: Path, rule, flights: list) -> str:
    """Scaffold a pytest test file for this .eml fixture."""
    fixture_name = eml_path.name
    airline_slug = rule.airline_name.lower().replace(".", "").replace(" ", "_").replace("-", "_")
    class_prefix = rule.airline_name.replace(".", "").replace(" ", "").replace("-", "")

    legs = []
    for i, f in enumerate(flights):
        dep = f.get("departure_datetime")
        arr = f.get("arrival_datetime")
        dep_str = (
            f"dt({dep.year}, {dep.month}, {dep.day}, {dep.hour}, {dep.minute})"
            if isinstance(dep, datetime)
            else "None"
        )
        arr_str = (
            f"dt({arr.year}, {arr.month}, {arr.day}, {arr.hour}, {arr.minute})"
            if isinstance(arr, datetime)
            else "None"
        )

        leg_label = f"{f.get('departure_airport', '?')} → {f.get('arrival_airport', '?')}  {f.get('flight_number', '?')}"
        legs.append((i, f, dep_str, arr_str, leg_label))

    lines = [
        '"""',
        f"Test: {rule.airline_name} parser.",
        "",
        f"Fixture: tests/fixtures/{fixture_name}",
        "  "
        + "  |  ".join(
            f"{f.get('departure_airport', '?')}→{f.get('arrival_airport', '?')} {f.get('flight_number', '?')}"
            for _, f, _, _, _ in legs
        ),
        "",
        "# TODO: describe the fixture briefly (forwarded? direct? PDF?)",
        '"""',
        "from datetime import UTC, datetime",
        "",
        "import pytest",
        "from conftest import load_eml_as_email_message",
        "",
        "",
        "def dt(year, month, day, hour, minute) -> datetime:",
        '    """UTC-aware datetime helper."""',
        "    return datetime(year, month, day, hour, minute, tzinfo=UTC)",
        "",
        "",
        '@pytest.fixture(scope="module")',
        f"def {airline_slug}_email():",
        f'    return load_eml_as_email_message("{fixture_name}")',
        "",
        "",
        '@pytest.fixture(scope="module")',
        f"def {airline_slug}_rule({airline_slug}_email):",
        "    from backend.parsers.builtin_rules import get_builtin_rules",
        "    from backend.parsers.engine import match_rule_to_email",
        "",
        "    rules = sorted(get_builtin_rules(), key=lambda r: r.priority, reverse=True)",
        f"    return match_rule_to_email({airline_slug}_email, rules)",
        "",
        "",
        '@pytest.fixture(scope="module")',
        f"def {airline_slug}_flights({airline_slug}_email, {airline_slug}_rule):",
        "    from backend.parsers.engine import extract_flights_from_email",
        "",
        f'    assert {airline_slug}_rule is not None, "No parsing rule matched the {rule.airline_name} fixture"',
        f"    return extract_flights_from_email({airline_slug}_email, {airline_slug}_rule)",
        "",
        "",
        "# ---------------------------------------------------------------------------",
        "# Rule matching",
        "# ---------------------------------------------------------------------------",
        "",
        f"class Test{class_prefix}RuleMatching:",
        f"    def test_rule_is_found(self, {airline_slug}_rule):",
        f"        assert {airline_slug}_rule is not None",
        "",
        f"    def test_rule_name(self, {airline_slug}_rule):",
        f'        assert {airline_slug}_rule.airline_name == "{rule.airline_name}"',
        "",
        "",
        "# ---------------------------------------------------------------------------",
        "# Flight count",
        "# ---------------------------------------------------------------------------",
        "",
        f"class Test{class_prefix}FlightCount:",
        f"    def test_flight_count(self, {airline_slug}_flights):",
        f"        assert len({airline_slug}_flights) == {len(flights)}",
        "",
    ]

    for i, f, dep_str, arr_str, label in legs:
        ordinal = (
            ["One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight"][i]
            if i < 8
            else str(i + 1)
        )
        lines += [
            "",
            "# ---------------------------------------------------------------------------",
            f"# Leg {i + 1}: {label}",
            "# ---------------------------------------------------------------------------",
            "",
            f"class Test{class_prefix}Leg{ordinal}:",
            f"    def test_flight_number(self, {airline_slug}_flights):",
            f'        assert {airline_slug}_flights[{i}]["flight_number"] == "{f.get("flight_number", "")}"',
            "",
            f"    def test_departure_airport(self, {airline_slug}_flights):",
            f'        assert {airline_slug}_flights[{i}]["departure_airport"] == "{f.get("departure_airport", "")}"',
            "",
            f"    def test_arrival_airport(self, {airline_slug}_flights):",
            f'        assert {airline_slug}_flights[{i}]["arrival_airport"] == "{f.get("arrival_airport", "")}"',
            "",
            f"    def test_airline_code(self, {airline_slug}_flights):",
            f'        assert {airline_slug}_flights[{i}]["airline_code"] == "{f.get("airline_code", "")}"',
            "",
            f"    def test_departure_datetime(self, {airline_slug}_flights):",
            f'        assert {airline_slug}_flights[{i}]["departure_datetime"] == {dep_str}',
            "",
            f"    def test_arrival_datetime(self, {airline_slug}_flights):",
            f'        assert {airline_slug}_flights[{i}]["arrival_datetime"] == {arr_str}',
            "",
        ]

    if flights and flights[0].get("booking_reference"):
        ref = (flights[0]["booking_reference"] or "").strip()
        lines += [
            "",
            "# ---------------------------------------------------------------------------",
            "# Booking reference",
            "# ---------------------------------------------------------------------------",
            "",
            f"class Test{class_prefix}BookingReference:",
            f"    def test_booking_reference(self, {airline_slug}_flights):",
            f"        for f in {airline_slug}_flights:",
            '            assert (f.get("booking_reference") or "").strip() != ""',
            "",
            f"    def test_booking_reference_value(self, {airline_slug}_flights):",
            f"        for f in {airline_slug}_flights:",
            f'            assert (f.get("booking_reference") or "").strip() == "{ref}"',
            "",
        ]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Parse a .eml file and inspect extracted flights.")
    parser.add_argument("eml", type=Path, help="Path to the .eml file")
    parser.add_argument("--generate-test", action="store_true", help="Scaffold a pytest test file")
    parser.add_argument("--out", type=Path, default=None, help="Write generated test to this file")
    args = parser.parse_args()

    if not args.eml.exists():
        print(f"Error: file not found: {args.eml}", file=sys.stderr)
        sys.exit(1)

    rule, flights = run(args.eml)

    if args.generate_test:
        if rule is None or not flights:
            print("Cannot generate test: no rule matched or no flights extracted.", file=sys.stderr)
            sys.exit(1)
        test_src = generate_test(args.eml, rule, flights)
        if args.out:
            args.out.write_text(test_src)
            print(f"  ✅  Test written to {args.out}\n")
        else:
            print("\n" + "=" * 60 + "  GENERATED TEST  " + "=" * 60)
            print(test_src)


if __name__ == "__main__":
    main()
