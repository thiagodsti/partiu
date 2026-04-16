"""
Email anonymizer — strips PII from failed emails while preserving
everything the parser needs (HTML structure, flight numbers, dates,
airports, airline markup, sender domain, subject line).

Output format matches email_cache.json fixture entries so tests
can be written directly against the anonymized files.
"""

import json
import re
from typing import Any

# ---------------------------------------------------------------------------
# PII patterns
# ---------------------------------------------------------------------------

# ALL-CAPS full names: 2+ words in all-caps (common in airline confirmations)
# Avoid matching short codes like "LA", "DY", "AD" (2-char airline codes)
_ALL_CAPS_NAME = re.compile(r"\b([A-Z]{2,}(?:\s+[A-Z]{2,})+)\b")

# Title-case names after salutation keywords ("Dear John Smith,")
_SALUTATION_NAME = re.compile(
    r"(?i)(?:dear|ol[aá]|hello|hi|hola|caro/a?|lieber?e?)\s+"
    r"([A-ZÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ][a-záàâãäéèêëíìîïóòôõöúùûüçñ]+"
    r"(?:\s+[A-ZÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ][a-záàâãäéèêëíìîïóòôõöúùûüçñ]+)+)"
)

# Title-case names after passenger/name labels ("Passenger: John Smith")
_PASSENGER_LABEL_NAME = re.compile(
    r"(?i)(?:passenger|passageiro|pasajero|nome|name|viaggiatore)[:\s]+"
    r"([A-ZÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ][a-záàâãäéèêëíìîïóòôõöúùûüçñ]+"
    r"(?:\s+[A-ZÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇÑ][a-záàâãäéèêëíìîïóòôõöúùûüçñ]+)+)"
)

# Email addresses
_EMAIL_ADDR = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")

# Local parts that are not PII (transactional senders)
_NON_PII_LOCAL = re.compile(
    r"^(?:no.?reply|donotreply|noreply|mailer.?daemon|postmaster|info|support|newsletter)$",
    re.IGNORECASE,
)

# Phone numbers: various international formats (exclude dot-separated formats like CPF)
_PHONE = re.compile(
    r"(?<!\d)"
    r"(\+?\d[\d\s\-()+]{7,18}\d)"
    r"(?!\d)"
)

# Brazilian CPF: 000.000.000-00
_CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")

# Brazilian RG-like patterns: 00.000.000-0
_RG = re.compile(r"\b\d{2}\.\d{3}\.\d{3}-\d\b")

# Credit/debit card numbers (4 groups of 4 digits, various separators)
_CARD = re.compile(r"\b\d{4}[\s\-]\d{4}[\s\-]\d{4}[\s\-]\d{4}\b")

# Passport numbers: letter + 6-8 digits
_PASSPORT = re.compile(r"\b[A-Z]{1,2}\d{6,8}\b")

# Booking/PNR references: 5-7 uppercase alphanumeric that look like confirmation codes
# Context-aware: must appear near trigger words
_BOOKING_CONTEXT = re.compile(
    r"(?i)(?:booking|reserv|confirm|locator|pnr|reference|código|código\s*de\s*reserva"
    r"|record\s*locator|reservation\s*code)\s*[:#]?\s*([A-Z0-9]{5,7})\b"
)

# Standalone 6-char alphanumeric that looks like a PNR (uppercase, mix of letters+digits)
_PNR_STANDALONE = re.compile(
    r"\b([A-Z]{1,4}[0-9]{1,4}[A-Z0-9]{0,2}|[0-9]{1,4}[A-Z]{1,4}[A-Z0-9]{0,2})\b"
)

# ---------------------------------------------------------------------------
# Flight number pattern — things we must NOT replace
# ---------------------------------------------------------------------------
_FLIGHT_NUMBER = re.compile(r"\b[A-Z]{1,3}\d{3,4}\b")


def _collect_flight_numbers(text: str) -> set[str]:
    return set(_FLIGHT_NUMBER.findall(text or ""))


def _replace_caps_names(text: str, flight_numbers: set[str]) -> str:
    def _sub(m: re.Match) -> str:
        val = m.group(0)
        if val in flight_numbers:
            return val
        # Skip 2-letter codes (likely airline IATA codes)
        parts = val.split()
        if all(len(p) <= 2 for p in parts):
            return val
        return "TEST PASSENGER"

    return _ALL_CAPS_NAME.sub(_sub, text)


def _extract_title_case_names(text: str) -> list[str]:
    """Collect title-case passenger names from salutation and label patterns."""
    names: list[str] = []
    for pattern in (_SALUTATION_NAME, _PASSENGER_LABEL_NAME):
        for m in pattern.finditer(text):
            names.append(m.group(1).strip())
    # Deduplicate, longest first so "John Michael Smith" replaces before "John Smith"
    seen: set[str] = set()
    result: list[str] = []
    for n in sorted(names, key=lambda s: len(s), reverse=True):
        if n not in seen:
            seen.add(n)
            result.append(n)
    return result


def _anonymize_text(
    text: str | None, flight_numbers: set[str], title_names: list[str] | None = None
) -> str | None:
    if not text:
        return text
    t = text
    # Title-case names (salutation-detected) — replace before all-caps pass
    for name in title_names or []:
        t = t.replace(name, "Test Passenger")
        t = t.replace(name.upper(), "TEST PASSENGER")
        t = t.replace(name.lower(), "test passenger")
    # ALL-CAPS names — before any placeholder that could re-match the caps-name pattern
    t = _replace_caps_names(t, flight_numbers)
    # Structured numeric patterns (CPF/RG must run before phone to avoid re-matching)
    t = _CPF.sub("000.000.000-00", t)
    t = _RG.sub("00.000.000-0", t)
    t = _CARD.sub("XXXX XXXX XXXX XXXX", t)

    def _email_sub(m: re.Match) -> str:
        local = m.group(0).split("@")[0]
        if _NON_PII_LOCAL.match(local):
            return m.group(0)
        return "test@example.com"

    t = _EMAIL_ADDR.sub(_email_sub, t)
    t = _BOOKING_CONTEXT.sub(lambda m: m.group(0).replace(m.group(1), "TESTRF"), t)

    # Phones last — regex excludes dots so CPF placeholders are not re-matched
    def _phone_sub(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) >= 7:
            return "+1 555 000 0000"
        return m.group(0)

    t = _PHONE.sub(_phone_sub, t)
    return t


def _anonymize_html(
    html: str | None, flight_numbers: set[str], title_names: list[str] | None = None
) -> str | None:
    """Anonymize HTML body while preserving tags/structure."""
    if not html:
        return html
    # Replace text nodes between tags, skipping tag attributes that carry structural info
    # Strategy: split on tags, anonymize only text runs
    parts = re.split(r"(<[^>]+>)", html)
    result = []
    for part in parts:
        if part.startswith("<"):
            # It's a tag — anonymize attribute values that look like PII
            def _email_sub_tag(m: re.Match) -> str:
                local = m.group(0).split("@")[0]
                if _NON_PII_LOCAL.match(local):
                    return m.group(0)
                return "test@example.com"

            p = _EMAIL_ADDR.sub(_email_sub_tag, part)
            p = _CPF.sub("000.000.000-00", p)
            result.append(p)
        else:
            result.append(_anonymize_text(part, flight_numbers, title_names) or part)
    return "".join(result)


def anonymize_email(email_msg: Any) -> dict:
    """
    Return an anonymized fixture dict for the given EmailMessage.

    The output matches the email_cache.json entry format:
        {message_id, sender, subject, date, body, html_body, pdf_attachments}

    PII removed: passenger names, email addresses, phone numbers, CPF/IDs,
                 credit card numbers.
    Preserved: HTML structure, flight numbers, dates, airports, sender domain,
               subject line, airline markup.
    """
    from .utils import dt_to_iso

    # Collect flight numbers from all text fields so we don't clobber them
    all_text = " ".join(
        filter(
            None,
            [
                email_msg.subject or "",
                email_msg.body or "",
                email_msg.html_body or "",
            ],
        )
    )
    flight_numbers = _collect_flight_numbers(all_text)
    title_names = _extract_title_case_names(all_text)

    # Sender: keep domain, anonymize local part
    sender = email_msg.sender or ""
    m = re.search(r"@([\w.-]+)", sender)
    anon_sender = f"no-reply@{m.group(1)}" if m else "no-reply@example.com"

    date_iso = dt_to_iso(email_msg.date) if email_msg.date else None

    return {
        "message_id": f"<anon-{hash(email_msg.message_id) & 0xFFFFFF:06x}@example.com>",
        "sender": anon_sender,
        "subject": email_msg.subject or "",  # subjects rarely contain PII
        "date": date_iso,
        "body": _anonymize_text(email_msg.body, flight_numbers, title_names),
        "html_body": _anonymize_html(email_msg.html_body, flight_numbers, title_names),
        "pdf_attachments": [],  # PDFs dropped — too hard to anonymize binary
    }


def save_anonymized_fixture(failed_id: str, eml_dir, email_msg: Any) -> None:
    """Save an anonymized JSON fixture alongside the .eml file."""
    try:
        fixture = anonymize_email(email_msg)
        out_path = eml_dir / f"{failed_id}_anonymized.json"
        out_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning(
            "Could not save anonymized fixture for %s: %s", failed_id, e
        )
