#!/usr/bin/env python3
"""
Semi-automated .eml anonymizer for airline confirmation emails.

Replaces the most common PII fields with safe fake values so the file can be
committed as a test fixture without leaking personal data.

What it replaces automatically:
  - Passenger name (common patterns: "Dear John Smith", "MR John Smith", "Passenger: John Smith")
  - Display names in From/To/Cc headers
  - Email addresses  →  bob.test@example.com
  - Phone numbers    →  +1-555-000-0000
  - Booking references in the subject line are left as-is (they are not PII)
  - Authentication/crypto headers (ARC, DKIM, SPF) stripped — useless for testing

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
import urllib.parse
from pathlib import Path

FAKE_EMAIL = "bob.test@example.com"
FAKE_NAME = "Bob Traveler"
FAKE_PHONE = "+1-555-000-0000"

# Headers that contain crypto signatures / routing metadata — never useful in test
# fixtures and often contain personal email addresses in SPF/DKIM results.
_DROP_HEADERS = {
    "arc-seal",
    "arc-message-signature",
    "arc-authentication-results",
    "authentication-results",
    "received-spf",
    "dkim-signature",
    "x-google-dkim-signature",
    "x-gm-message-state",
    "x-gm-gg",
    "x-gm-features",
    "x-received",
    "x-forwarded-to",
    "x-original-to",
}

# ---------------------------------------------------------------------------
# PII detection patterns
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

_PHONE_RE = re.compile(r"(?<!\d)(\+?\d[\d\s\-\(\)\.]{7,}\d)(?!\d)")

# "Dear John Smith," / "Olá John Smith," / "MR John Smith" / "Dr. John Smith"
_SALUTATION_RE = re.compile(
    r"(?i)(dear|ol[aá]|hello|hi|hola|caro/a?|lieber?e?|mr\.?|mrs\.?|ms\.?|dr\.?|prof\.?)\s+"
    r"([A-ZÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ][a-záàâãäéèêëíìîïóòôõöúùûüçñ]+"
    r"(?:\s+[A-ZÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ][a-záàâãäéèêëíìîïóòôõöúùûüçñ]+)+)"
)

# "Passenger: John Smith" / "Passageiro: John Smith" / "Nome: John Smith"
_PASSENGER_LABEL_RE = re.compile(
    r"(?i)(passenger|passageiro|pasajero|nome|name|viaggiatore|customer[:\s]+contact[:\s]+name)[:\s]+"
    r"([A-ZÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ][a-záàâãäéèêëíìîïóòôõöúùûüçñ]+"
    r"(?:\s+[A-ZÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ][a-záàâãäéèêëíìîïóòôõöúùûüçñ]+)+)"
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

# Display name in "Display Name <email@domain>" format
_DISPLAY_NAME_RE = re.compile(r'^"?([^"<]+?)"?\s*<')

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
    "WIZZ",
    "AIR",
    "RYANAIR",
    "LATAM",
    "LUFTHANSA",
    "NORWEGIAN",
}


def _extract_display_name(header_value: str) -> str | None:
    """Extract display name from 'Display Name <email>' header value."""
    m = _DISPLAY_NAME_RE.match(header_value.strip())
    if m:
        name = m.group(1).strip()
        # Must look like at least two words (first + last name)
        if len(name.split()) >= 2:
            return name
    return None


def _extract_probable_names(text: str, extra_names: list[str] | None = None) -> list[str]:
    """Return a list of candidate real names found in the text.

    Also expands each name into all 2+ word sub-sequences so partial occurrences
    like "Ramos da Silva" are caught even when the full name is "Diego Ramos da Silva".
    """
    raw: list[str] = list(extra_names or [])
    for m in _SALUTATION_RE.finditer(text):
        raw.append(m.group(2).strip())
    for m in _PASSENGER_LABEL_RE.finditer(text):
        raw.append(m.group(2).strip())
    for m in _ALLCAPS_NAME_RE.finditer(text):
        candidate = m.group(1).strip()
        words = candidate.split()
        if any(w in _SKIP_WORDS for w in words):
            continue
        raw.append(candidate)

    # Expand to all 2+ word sub-sequences of each detected name, but only for
    # short names (≤5 words, no newlines) that look like actual person names.
    expanded: list[str] = []
    for name in raw:
        # Skip multi-line or sentence-like strings
        if "\n" in name or "\r" in name or len(name) > 60:
            continue
        words = name.split()
        if len(words) > 5:
            continue
        expanded.append(name)
        for start in range(len(words)):
            for end in range(start + 2, len(words) + 1):
                expanded.append(" ".join(words[start:end]))

    # deduplicate, longest first (so "John Michael Smith" is replaced before "John Smith")
    seen: set[str] = set()
    result: list[str] = []
    for n in sorted(expanded, key=len, reverse=True):
        n = n.strip()
        if n and n not in seen:
            seen.add(n)
            result.append(n)
    return result


def _anonymize_text(
    text: str,
    real_names: list[str],
    fake_name: str,
    fake_email: str,
    personal_emails: set[str] | None = None,
) -> str:
    # Replace real names first (longest first, already sorted)
    for name in real_names:
        text = text.replace(name, fake_name)
        text = text.replace(name.upper(), fake_name.upper())
        text = text.replace(name.lower(), fake_name.lower())
        # URL-encoded variants (e.g. "Ramos%20da%20Silva" in href attributes)
        encoded = urllib.parse.quote(name)
        if encoded != name:
            text = text.replace(encoded, urllib.parse.quote(fake_name))
        # Also handle spaces encoded as +
        encoded_plus = name.replace(" ", "+")
        if encoded_plus != name:
            text = text.replace(encoded_plus, fake_name.replace(" ", "+"))

    # Replace email addresses (but skip example.com addresses we already inserted)
    _personal = personal_emails or set()

    def _replace_email(m: re.Match) -> str:
        addr = m.group(0)
        if "example.com" in addr or "test@" in addr:
            return addr
        if addr.lower() in _personal:
            return fake_email
        local = fake_email.split("@")[0]
        return f"{local}@{addr.split('@')[-1]}"

    text = _EMAIL_RE.sub(_replace_email, text)

    # Replace phone numbers
    text = _PHONE_RE.sub(FAKE_PHONE, text)

    # Replace partially-masked emails like "T****@G****.COM"
    text = _MASKED_EMAIL_RE.sub(fake_email, text)

    # Replace personal email local parts that appear in URL paths (e.g. LinkedIn usernames)
    fake_local = fake_email.split("@")[0]
    for addr in _personal:
        local = addr.split("@")[0]
        if len(local) >= 5 and local not in (
            "noreply",
            "no-reply",
            "donotreply",
            "info",
            "support",
        ):
            text = text.replace(f"/in/{local}", f"/in/{fake_local}")
            text = text.replace(f"/u/{local}", f"/u/{fake_local}")

    return text


def _anonymize_header_value(
    value: str,
    is_recipient: bool,
    personal_emails: set[str],
    fake_email: str,
) -> str:
    """Replace emails in a header value; always fully replace personal emails."""

    def _replace(m: re.Match) -> str:
        addr = m.group(0)
        if "example.com" in addr:
            return addr
        if is_recipient or addr.lower() in personal_emails:
            return fake_email
        local = fake_email.split("@")[0]
        return f"{local}@{addr.split('@')[-1]}"

    return _EMAIL_RE.sub(_replace, value)


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

    # Extract display names from From/To/Cc headers — these are real names we
    # must replace even when they don't appear near a salutation keyword.
    header_names: list[str] = []
    for header in ("From", "Reply-To", "To", "Cc"):
        if msg[header]:
            dn = _extract_display_name(msg[header])
            if dn:
                header_names.append(dn)

    real_names = _extract_probable_names(all_text, extra_names=header_names)
    if real_names:
        print(f"  Detected probable names: {real_names}")
    else:
        print("  No names auto-detected. If the email contains a passenger name,")
        print("  search for it manually and pass --name 'Real Name' to replace it.")

    # Collect personal email addresses: recipient headers + From (could be a forwarder)
    personal_emails: set[str] = set()
    for header in ("To", "Cc", "Delivered-To", "From", "Reply-To"):
        if msg[header]:
            for m in _EMAIL_RE.finditer(msg[header]):
                personal_emails.add(m.group(0).lower())

    # -----------------------------------------------------------------------
    # Drop noisy authentication / routing headers that serve no testing purpose
    # and often leak real email addresses (SPF results, ARC, DKIM, etc.)
    # -----------------------------------------------------------------------
    for h in list({k.lower() for k in msg.keys()}):
        if h in _DROP_HEADERS:
            while h.title().replace("-", "-") in msg or h in msg:
                # msg.keys() returns original-cased keys; delete by that case
                break
    # Deletion must use original-cased keys
    for key in list(msg.keys()):
        if key.lower() in _DROP_HEADERS:
            del msg[key]

    # -----------------------------------------------------------------------
    # Anonymize structured headers
    # -----------------------------------------------------------------------
    for header in ("To", "Cc", "Delivered-To", "Return-Path"):
        if msg[header]:
            val = _anonymize_header_value(msg[header], True, personal_emails, fake_email)
            # Strip display name entirely for recipient headers
            val = _DISPLAY_NAME_RE.sub("<", val)
            msg.replace_header(header, val)

    for header in ("From", "Reply-To"):
        if msg[header]:
            val = _anonymize_header_value(msg[header], False, personal_emails, fake_email)
            # Replace display name with fake name
            val = _DISPLAY_NAME_RE.sub(f"{fake_name} <", val)
            msg.replace_header(header, val)

    # Anonymize Received headers (leak IP / real email)
    received = msg.get_all("Received") or []
    while "Received" in msg:
        del msg["Received"]
    for r in received:
        r = _EMAIL_RE.sub(
            lambda m: fake_email if "example.com" not in m.group(0) else m.group(0), r
        )
        msg["Received"] = r

    # -----------------------------------------------------------------------
    # Anonymize body parts
    # -----------------------------------------------------------------------
    for part in msg.walk():
        ct = part.get_content_type()
        if ct not in ("text/plain", "text/html"):
            continue
        raw_payload = part.get_payload(decode=True)
        if not raw_payload or not isinstance(raw_payload, bytes):
            continue
        text = raw_payload.decode("utf-8", errors="replace")
        text = _anonymize_text(text, real_names, fake_name, fake_email, personal_emails)
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


def main() -> None:
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

    print(f"\n  Written to {out}")
    print()
    print("  Please review the output manually before committing:")
    print("      - Passenger name in unusual HTML locations")
    print("      - Passport / ID numbers")
    print("      - Loyalty programme numbers")
    print("      - Credit card last 4 digits")
    print()
    print("  Next step:")
    print(f"      uv run python tools/parse_eml.py {out}")
    print()


if __name__ == "__main__":
    main()
