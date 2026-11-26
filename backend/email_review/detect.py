"""What the review page shows about an email: hints and the lines that matter.

Pure functions over the email's text. Nothing here decides anything: a hint is
something that *looks like* a flight number, an airport code, a date, a time or
a booking code, offered to the traveller as a chip to click into a form field.
That is also why the extraction can be generous where the parsers are strict —
a wrong chip costs a glance, never a wrong flight.
"""

import re

from ..parsers.airport_grounding import airport_index
from ..parsers.shared import extract_booking_reference
from ..utils.dates import validate_flight_number

_MAX_EACH = 8
_MAX_EXCERPT_LINES = 14
_MAX_LINE = 220

# Two or more digits, and not glued to a "#" or a word character: "#FF7020" is a
# colour in the email's CSS, not flight FF7020.
_FLIGHT_NUMBER = re.compile(r"(?<![#\w])((?:[A-Z]{2}|[A-Z]\d|\d[A-Z])\s?\d{2,4})(?!\w)")
# Aircraft types print exactly like flight numbers ("A320", "B737", "E190").
_AIRCRAFT = re.compile(r"^(?:[AB]\d{3}|E\d{3})$")
# Three capitals that are airport codes but almost never mean one in a booking
# mail: months, currencies, countries.
_NOT_AIRPORTS = frozenset(
    "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC "
    "EUR USD GBP SEK NOK DKK CHF BRL ARS CLP PLN CZK HUF TRY JPY CNY AUD CAD MXN "
    "USA "
    # Portuguese, Spanish and English words in the corpus's booking mail:
    # "ida" (outbound), "seu" (your), TAM (LATAM's old name), "pis" (tax id).
    "IDA SEU TAM PIS VOO".split()
)
_CSS_BLOCK = re.compile(r"\{[^{}]*\}")
# Markup that survives the HTML-to-text pass in some mails: whole tags, and the
# tail of a tag cut at a line break ("style='color:#1b0088;'>LA4671</b>").
_TAG = re.compile(r"<[^>]*>|^[^<>]*?\b(?:style|class|href|src)=[^>]*>", re.MULTILINE)
_CODE = re.compile(r"(?<![A-Za-z])([A-Z]{3})(?![A-Za-z])")
_TIME = re.compile(r"(?<![\d:])([01]?\d|2[0-3])[:hH]([0-5]\d)(?![\d:])")
_MONTHS = r"jan|feb|fev|mar|apr|abr|may|mai|maj|jun|jul|aug|ago|sep|set|oct|out|okt|nov|dec|dez"
_DATE = re.compile(
    rf"\b(\d{{4}}-\d{{2}}-\d{{2}}"
    rf"|\d{{1,2}}[/.]\d{{1,2}}[/.]\d{{2,4}}"
    # A trailing year must not be the hour of a time: "16 NOV 15:40".
    rf"|\d{{1,2}}\s?(?:{_MONTHS})[a-zç]*\.?(?:\s?\d{{2,4}}(?![\d:]))?"
    rf"|(?:{_MONTHS})[a-zç]*\.?\s\d{{1,2}}(?:,?\s\d{{4}})?)\b",
    re.IGNORECASE,
)


def _unique(values, limit=_MAX_EACH) -> list[str]:
    seen: list[str] = []
    for v in values:
        if v and v not in seen:
            seen.append(v)
        if len(seen) >= limit:
            break
    return seen


def clean(text: str) -> str:
    """The email's text without inline CSS, where colours and sizes look like
    flight numbers and airport codes."""
    return _TAG.sub(" ", _CSS_BLOCK.sub(" ", text or ""))


def normalise_flight_number(fn: str) -> str:
    """ "TP 0788" and "TP788" are one flight."""
    fn = fn.replace(" ", "").upper()
    return re.sub(r"^([A-Z0-9]{2})0+(?=\d)", r"\1", fn)


def all_flight_numbers(text: str) -> list[str]:
    """Every flight-number-shaped token, uncapped (for the known-flight check)."""
    found = (m.group(1).replace(" ", "") for m in _FLIGHT_NUMBER.finditer(text))
    return list(
        dict.fromkeys(
            fn
            for fn in found
            if validate_flight_number(fn) and not _AIRCRAFT.match(fn) and fn[2:].strip("0")
        )
    )


def flight_numbers(text: str) -> list[str]:
    return _unique(all_flight_numbers(text))


def airport_codes(text: str) -> list[str]:
    """Three-letter codes printed as words of their own that are real airports."""
    codes, _, _ = airport_index()
    return _unique(c for c in _CODE.findall(text) if c in codes and c not in _NOT_AIRPORTS)


def dates(text: str) -> list[str]:
    return _unique(" ".join(m.group(1).split()) for m in _DATE.finditer(text))


def times(text: str) -> list[str]:
    return _unique(f"{int(h):02d}:{m}" for h, m in _TIME.findall(text))


def _booking_reference(body: str, subject: str, text: str) -> str | None:
    """The shared extractor's code, unless it is plainly a word: a real code
    never also appears in lower case ("OFERTAS" beside "Ofertas")."""
    # A code in the subject ("Confirmação ... - JD8B6D") is the booking's own:
    # letters and digits, 5 to 8 long. Read it first; the body's labels can
    # point at a banner word ("ALUGUE").
    in_subject = [
        t
        for t in re.findall(r"\b[A-Z0-9]{5,8}\b", subject)
        if re.search(r"[A-Z]", t) and re.search(r"\d", t)
    ]
    if in_subject:
        return in_subject[-1]
    ref = extract_booking_reference(body, subject) or None
    if ref and re.search(rf"\b{re.escape(ref)}\b", text, re.IGNORECASE | re.UNICODE):
        if any(m != ref for m in re.findall(rf"\b{re.escape(ref)}\b", text, re.IGNORECASE)):
            return None
    return ref


def hints(subject: str, body: str) -> dict:
    """Everything worth offering as a chip, plus the lines it was found on."""
    body = clean(body)
    text = f"{subject}\n{body}"
    found = {
        "flight_numbers": flight_numbers(text),
        "airports": airport_codes(text),
        "dates": dates(text),
        "times": times(text),
        "booking_reference": _booking_reference(body, subject, text),
    }
    found["excerpt"] = excerpt(body, found)
    return found


def excerpt(body: str, found: dict) -> list[str]:
    """The lines of the email that carry a hint, in order, trimmed."""
    needles = [*found["flight_numbers"], *found["airports"]]
    if found.get("booking_reference"):
        needles.append(found["booking_reference"])
    lines: list[str] = []
    for raw in (body or "").splitlines():
        line = " ".join(raw.split())
        if not line or line in lines:
            continue
        compact = line.replace(" ", "")
        if (
            any(n in line or n in compact for n in needles)
            or _TIME.search(line)
            and _DATE.search(line)
        ):
            lines.append(line[:_MAX_LINE])
        if len(lines) >= _MAX_EXCERPT_LINES:
            break
    return lines
