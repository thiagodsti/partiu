"""
Flight email parsing engine.

Main entry point: extract_flights_from_email()

Flow:
  1. Try the per-airline extractor (HTML, regex, PDF — handled internally).
  2. Also try the generic PDF extractor and merge any richer fields it finds.
"""

import calendar
import logging
import re
from datetime import date as date_type
from datetime import datetime

from .email_connector import EmailMessage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Multilingual month-name → month-number map
# ---------------------------------------------------------------------------


def _build_month_map() -> dict[str, int]:
    """
    Build a lowercase month-name → month-number mapping.

    English names and abbreviations are generated from the standard library so
    we don't have to hardcode them. Only the non-English extras are listed
    explicitly, grouped by language.
    """
    mapping: dict[str, int] = {}

    # English — full names ("january") and 3-letter abbreviations ("jan")
    for n in range(1, 13):
        mapping[calendar.month_name[n].lower()] = n
        mapping[calendar.month_abbr[n].lower()] = n
    mapping["sept"] = 9  # common 4-letter variant not produced by calendar

    # Non-English month names (only entries not already covered by English)
    _EXTRA: dict[str, int] = {
        # Portuguese
        "janeiro": 1,
        "fevereiro": 2,
        "março": 3,
        "abril": 4,
        "maio": 5,
        "junho": 6,
        "julho": 7,
        "agosto": 8,
        "setembro": 9,
        "outubro": 10,
        "novembro": 11,
        "dezembro": 12,
        "fev": 2,
        "abr": 4,
        "mai": 5,
        "ago": 8,
        "set": 9,
        "out": 10,
        "dez": 12,
        # Spanish
        "enero": 1,
        "febrero": 2,
        "marzo": 3,
        "mayo": 5,
        "junio": 6,
        "julio": 7,
        "septiembre": 9,
        "octubre": 10,
        "noviembre": 11,
        "diciembre": 12,
        "ene": 1,
        "dic": 12,
        # German
        "märz": 3,
        "oktober": 10,
        "dezember": 12,
        "mär": 3,
        # Scandinavian (Swedish / Norwegian / Danish)
        "marts": 3,
        "maj": 5,
        "juni": 6,
        "juli": 7,
        "augusti": 8,
        "okt": 10,
        "des": 12,
        # Turkish — both the diacritic spelling the emails use and the folded
        # form, because some senders strip the diacritics.
        "ocak": 1,
        "şubat": 2,
        "subat": 2,
        "mart": 3,
        "nisan": 4,
        "mayıs": 5,
        "mayis": 5,
        "haziran": 6,
        "temmuz": 7,
        "ağustos": 8,
        "agustos": 8,
        "eylül": 9,
        "eylul": 9,
        "ekim": 10,
        "kasım": 11,
        "kasim": 11,
        "aralık": 12,
        "aralik": 12,
    }
    mapping.update(_EXTRA)
    return mapping


MONTH_MAP = _build_month_map()


def parse_flight_date(raw: str) -> date_type | None:
    """
    Parse a date string that may use multilingual month names.
    Handles formats like "16 de mar. de 2026", "16 Mar 2026", "2026-03-16",
    and day-of-week prefixes like "Wed, 23 Apr 25".
    """
    raw = raw.strip()
    # Strip leading day-of-week: "Wed, 23 Apr 25" → "23 Apr 25"
    raw = re.sub(r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*,?\s+", "", raw, flags=re.IGNORECASE)

    # ISO and common numeric formats (with year)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    # "16 de mar. de 2026" or "16 Mar 2026"
    m = re.match(r"(\d{1,2})\s+(?:de\s+)?([A-Za-zÀ-ÿ]+)\.?\s+(?:de\s+)?(\d{4})", raw)
    if m:
        month = MONTH_MAP.get(m.group(2).lower().rstrip("."))
        if month:
            try:
                return date_type(int(m.group(3)), month, int(m.group(1)))
            except ValueError:
                pass

    # "Mar 16, 2026"
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", raw)
    if m:
        month = MONTH_MAP.get(m.group(1).lower())
        if month:
            try:
                return date_type(int(m.group(3)), month, int(m.group(2)))
            except ValueError:
                pass

    # Last resort: Python's strptime with locale month names
    # Includes compact no-space variants (24JAN2019, 24JAN19) and 2-digit years
    for fmt in ("%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%d%b%Y", "%d%b%y", "%d %b %y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    return None


def match_rule_to_email(email_msg: EmailMessage, rules):
    """
    Find the first airline rule matching the email's sender (and optionally subject).

    Also checks From:/Subject: lines embedded in forwarded message headers, so
    emails forwarded via Gmail ("---------- Forwarded message ---------") still
    match the original sender's rule.
    """
    senders = candidate_senders(email_msg)
    subjects = candidate_subjects(email_msg)

    from .builtin_rules import SUBJECT_PATTERN

    for rule in rules:
        try:
            if not any(re.search(rule.sender_pattern, s, re.IGNORECASE) for s in senders):
                continue
            if not any(re.search(SUBJECT_PATTERN, s, re.IGNORECASE) for s in subjects):
                continue
            return rule
        except re.error as e:
            logger.warning("Invalid regex in rule %s: %s", rule.airline_name, e)
    return None


# Forwarded-message header labels. Gmail (and most webmail) localises these to
# the *forwarder's* UI language, not the original sender's — a Brazilian user
# forwarding a Ryanair itinerary produces "De:", not "From:". Matching only the
# English label meant those emails reached no airline rule at all.
_FORWARDED_FROM_LABELS = r"From|De|Von|Fr[aå]n|Fra|Da|Van|Exp[eé]diteur|Remitente|L[aä]hettäjä"
_FORWARDED_SUBJECT_LABELS = r"Subject|Assunto|Asunto|Betreff|[ÄA]mne|Emne|Oggetto|Objet|Aihe"

_forwarded_from_re = re.compile(
    rf"^(?:{_FORWARDED_FROM_LABELS}):\s*(.+)$", re.MULTILINE | re.IGNORECASE
)
_forwarded_subject_re = re.compile(
    rf"^(?:{_FORWARDED_SUBJECT_LABELS}):\s*(.+)$", re.MULTILINE | re.IGNORECASE
)


def _extract_forwarded_senders(body: str) -> list[str]:
    """Extract From: addresses from forwarded-message headers in the email body."""
    return _forwarded_from_re.findall(body[:5000])


def _extract_forwarded_subjects(body: str) -> list[str]:
    """Extract Subject: lines from forwarded-message headers in the email body."""
    return _forwarded_subject_re.findall(body[:5000])


def _forwarded_sources(email_msg) -> list[str]:
    """Texts that may carry an original header block.

    The rendered body is first. The raw MIME copy is read too: some forwarders
    put the quoted headers only in the text/plain part, which
    ``get_email_body_and_html`` drops when an HTML part is present.
    """
    sources = [getattr(email_msg, "body", "") or ""]
    raw = getattr(email_msg, "raw_eml", None)
    if isinstance(raw, bytes):
        sources.append(raw.decode("utf-8", errors="replace"))
    elif raw:
        sources.append(str(raw))
    return sources


def _unique(values) -> list[str]:
    """Drop empty and duplicate candidates without disturbing their order."""
    return list(dict.fromkeys(v.strip() for v in values if v and v.strip()))


def candidate_senders(email_msg) -> list[str]:
    """Every sender an email could honestly be from: the envelope From plus the
    original From lines preserved in a forwarded body.

    Forwarding replaces the envelope sender with the forwarder, so a
    sender-gated reader that only looks at ``email_msg.sender`` silently skips
    the booking it was written for. Airline rules have always used this list;
    the lodging and rental readers use it too.
    """
    candidates = [getattr(email_msg, "sender", "") or ""]
    for source in _forwarded_sources(email_msg):
        candidates.extend(_extract_forwarded_senders(source))
    return _unique(candidates)


def candidate_subjects(email_msg) -> list[str]:
    """The same idea for subjects: the outer Fwd: line and the original one."""
    candidates = [getattr(email_msg, "subject", "") or ""]
    for source in _forwarded_sources(email_msg):
        candidates.extend(_extract_forwarded_subjects(source))
    return _unique(candidates)


def extract_flights_from_email(email_msg: EmailMessage, rule) -> list[dict]:
    """
    Extract flight data from an email that has been matched to an airline rule.

    Calls ``rule.extractor(email_msg, rule)`` — the per-airline unified callable
    set by ``get_builtin_rules()``.  PDF attachments are the individual rule's
    business (via ``gds_eticket`` for receipts, or its own reader): the generic
    PDF pattern that used to be merged in here contributed nothing across the
    whole email corpus while remaining able to invent a leg from any table that
    happened to look like an itinerary.
    """
    extractor = getattr(rule, "extractor", None)
    if extractor is None:
        return []

    try:
        return extractor(email_msg, rule)
    except Exception:
        logger.debug(
            "Extractor for '%s' raised an exception",
            rule.airline_name,
            exc_info=True,
        )
        return []


def merge_flights(primary: list[dict], secondary: list[dict]) -> list[dict]:
    """
    Merge ``secondary`` results into ``primary`` by filling empty fields.

    Matches flights by (flight_number, departure_airport, arrival_airport).
    Flights in ``secondary`` that have no match in ``primary`` are appended.
    """
    if not primary:
        return secondary
    if not secondary:
        return primary

    def _key(f: dict):
        return (
            f.get("flight_number", "").replace(" ", ""),
            f.get("departure_airport", ""),
            f.get("arrival_airport", ""),
        )

    primary_map = {_key(f): f for f in primary}
    for sec in secondary:
        k = _key(sec)
        if k in primary_map:
            pri = primary_map[k]
            for field_name, val in sec.items():
                if val and not pri.get(field_name):
                    pri[field_name] = val
        else:
            primary.append(sec)

    return primary
