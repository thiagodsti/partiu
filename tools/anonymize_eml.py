#!/usr/bin/env python3
"""
Semi-automated .eml anonymizer for airline confirmation emails.

Replaces the most common PII fields with safe fake values so the file can be
committed as a test fixture without leaking personal data.

What it replaces automatically:
  - Passenger name (common patterns: "Dear John Smith", "Passenger: John Smith")
  - Email addresses  →  bob.test@example.com
  - Phone numbers    →  +1-555-000-0000
  - Booking references in the subject line are left as-is (they are not PII)

What you must review manually afterwards:
  - The passenger name may appear in unexpected places in the HTML
  - Passport / ID numbers (rare in emails but possible)
  - Loyalty programme numbers
  - Credit card last 4 digits
  - Home address (rare)

Usage:
    python tools/anonymize_eml.py original.eml
    python tools/anonymize_eml.py original.eml --out backend/tests/fixtures/myairline_anonymized.eml
    python tools/anonymize_eml.py original.eml --name "Alice Traveler" --email "alice.test@example.com"
"""

import argparse
import email as stdlib_email
import email.policy
import quopri
import re
import sys
from pathlib import Path

FAKE_EMAIL = "bob.test@example.com"
FAKE_NAME = "Bob Traveler"
FAKE_PHONE = "+1-555-000-0000"

# ---------------------------------------------------------------------------
# PII detection patterns
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

_PHONE_RE = re.compile(r"(?<!\d)(\+?\d[\d\s\-\(\)\.]{7,}\d)(?!\d)")

# "Dear John Smith," / "Olá John Smith," / "Hello John Smith"
_SALUTATION_RE = re.compile(
    r"(?i)(dear|ol[aá]|hello|hi|hola|caro/a?|lieber?e?)\s+([A-ZÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ][a-záàâãäéèêëíìîïóòôõöúùûüçñ]+(?:\s+[A-ZÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ][a-záàâãäéèêëíìîïóòôõöúùûüçñ]+)+)"
)

# "Passenger: John Smith" / "Passageiro: John Smith" / "Nome: John Smith"
_PASSENGER_LABEL_RE = re.compile(
    r"(?i)(passenger|passageiro|pasajero|nome|name|viaggiatore)[:\s]+([A-ZÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ][a-záàâãäéèêëíìîïóòôõöúùûüçñ]+(?:\s+[A-ZÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ][a-záàâãäéèêëíìîïóòôõöúùûüçñ]+)+)"
)

# ALL-CAPS names like "JOHN MICHAEL SMITH" (2+ words, 2+ chars each, letters only incl. accented)
# Common in airline boarding pass sections and e-ticket PDFs
_ALLCAPS_NAME_RE = re.compile(
    r"\b([A-ZÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ]{2,}(?:[ \t]+[A-ZÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ]{2,}){1,5})\b"
)

# Partially-masked emails like "T****@G****.COM" or "jo**@gm***.com"
_MASKED_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9][*A-Za-z0-9]*\*+[*A-Za-z0-9]*@[A-Za-z0-9][*A-Za-z0-9]*\*+[*A-Za-z0-9]*\.[A-Za-z]{2,}\b"
)


def _extract_probable_names(text: str) -> list[str]:
    """Return a list of candidate real names found in the text."""
    names = []
    for m in _SALUTATION_RE.finditer(text):
        names.append(m.group(2).strip())
    for m in _PASSENGER_LABEL_RE.finditer(text):
        names.append(m.group(2).strip())
    for m in _ALLCAPS_NAME_RE.finditer(text):
        candidate = m.group(1).strip()
        # Skip obvious non-names: all-caps HTML tags, common airline/airport keywords
        _SKIP_WORDS = {
            "FROM",
            "TO",
            "DATE",
            "TIME",
            "FLIGHT",
            "CLASS",
            "SEAT",
            "GATE",
            "BOARDING",
            "ARRIVAL",
            "DEPARTURE",
            "TERMINAL",
            "STATUS",
            "CABIN",
            "ECONOMY",
            "BUSINESS",
            "FIRST",
            "CHECK",
            "IN",
            "OUT",
            "AM",
            "PM",
            "OK",
            "PDF",
            "HTML",
            "UTF",
            "MIME",
            "IATA",
            "PNR",
            "HTTP",
            "HTTPS",
        }
        words = candidate.split()
        if any(w in _SKIP_WORDS for w in words):
            continue
        names.append(candidate)
    # deduplicate, longest first (so "John Michael Smith" is replaced before "John Smith")
    seen = set()
    result = []
    for n in sorted(names, key=len, reverse=True):
        if n not in seen:
            seen.add(n)
            result.append(n)
    return result


def _anonymize_text(text: str, real_names: list[str], fake_name: str, fake_email: str) -> str:
    # Replace real names first (longest first, already sorted)
    for name in real_names:
        text = text.replace(name, fake_name)
        # also try upper/lower variants
        text = text.replace(name.upper(), fake_name.upper())
        text = text.replace(name.lower(), fake_name.lower())

    # Replace email addresses (but skip example.com addresses we already inserted)
    def _replace_email(m):
        addr = m.group(0)
        if "example.com" in addr or "test@" in addr:
            return addr
        return fake_email

    text = _EMAIL_RE.sub(_replace_email, text)

    # Replace phone numbers
    text = _PHONE_RE.sub(FAKE_PHONE, text)

    # Replace partially-masked emails like "T****@G****.COM"
    text = _MASKED_EMAIL_RE.sub(fake_email, text)

    return text


def anonymize(src: Path, fake_name: str, fake_email: str) -> bytes:
    raw = src.read_bytes()
    msg = stdlib_email.message_from_bytes(raw, policy=stdlib_email.policy.compat32)

    # First pass: collect real names from plain-text body
    all_text = ""
    for part in msg.walk():
        ct = part.get_content_type()
        if ct in ("text/plain", "text/html"):
            payload = part.get_payload(decode=True)
            if payload and isinstance(payload, bytes):
                all_text += payload.decode("utf-8", errors="replace") + "\n"

    real_names = _extract_probable_names(all_text)
    if real_names:
        print(f"  Detected probable names: {real_names}")
    else:
        print("  No names auto-detected. If the email contains a passenger name,")
        print("  search for it manually and pass --name 'Real Name' to replace it.")

    # Anonymize headers
    for header in ("From", "To", "Cc", "Reply-To", "Delivered-To", "Return-Path"):
        if msg[header]:
            msg.replace_header(
                header,
                _EMAIL_RE.sub(
                    lambda m: fake_email if "example.com" not in m.group(0) else m.group(0),
                    msg[header],
                ),
            )

    # Anonymize Received headers (leak IP / real email)
    received = msg.get_all("Received") or []
    while "Received" in msg:
        del msg["Received"]
    for r in received:
        r = _EMAIL_RE.sub(
            lambda m: fake_email if "example.com" not in m.group(0) else m.group(0), r
        )
        msg["Received"] = r

    # Anonymize body parts
    for part in msg.walk():
        ct = part.get_content_type()
        if ct not in ("text/plain", "text/html"):
            continue
        raw_payload = part.get_payload(decode=True)
        if not raw_payload or not isinstance(raw_payload, bytes):
            continue
        text = raw_payload.decode("utf-8", errors="replace")
        text = _anonymize_text(text, real_names, fake_name, fake_email)
        charset = part.get_content_charset() or "utf-8"
        cte = part.get("Content-Transfer-Encoding", "").lower()
        new_payload = text.encode(charset, errors="replace")
        if cte == "quoted-printable":
            part.set_payload(quopri.encodestring(new_payload).decode("ascii"))
        elif cte == "base64":
            import base64

            part.set_payload(base64.encodebytes(new_payload).decode("ascii"))
        else:
            part.set_payload(new_payload, charset=charset)

    return msg.as_bytes()


def main():
    parser = argparse.ArgumentParser(
        description="Anonymize PII from a .eml file for use as a test fixture."
    )
    parser.add_argument("eml", type=Path, help="Path to the original .eml file")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path (default: <name>_anonymized.eml alongside the input)",
    )
    parser.add_argument(
        "--name", default=FAKE_NAME, help=f"Fake name to substitute (default: {FAKE_NAME!r})"
    )
    parser.add_argument(
        "--email", default=FAKE_EMAIL, help=f"Fake email to substitute (default: {FAKE_EMAIL!r})"
    )
    args = parser.parse_args()

    if not args.eml.exists():
        print(f"Error: file not found: {args.eml}", file=sys.stderr)
        sys.exit(1)

    out = args.out or args.eml.with_name(args.eml.stem + "_anonymized.eml")

    print(f"\n  Anonymizing {args.eml} …\n")
    result = anonymize(args.eml, args.name, args.email)
    out.write_bytes(result)

    print(f"\n  ✅  Written to {out}")
    print()
    print("  ⚠️  Please review the output manually before committing:")
    print("      - Passenger name in unusual HTML locations")
    print("      - Passport / ID numbers")
    print("      - Loyalty programme numbers")
    print("      - Credit card last 4 digits")
    print()
    print("  Next step:")
    print(f"      python tools/parse_eml.py {out}")
    print()


if __name__ == "__main__":
    main()
