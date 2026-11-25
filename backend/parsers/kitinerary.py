"""KDE Itinerary's extractor as an extraction tier.

KItinerary (https://invent.kde.org/pim/kitinerary) is KDE's open-source
itinerary extractor: ~370 per-provider extractors plus generic readers for
schema.org markup, IATA boarding-pass barcodes, Apple Wallet passes and PDFs.
It covers carriers Partiu has no rule for (easyJet, KLM, Swiss, Eurowings, Aer
Lingus, IndiGo, ...) and is the same structural kind of reader as ours: a
per-template extractor that finds what it knows or returns nothing — not the
proximity guessing this codebase removed.

**Where it sits.** After the airline rule, the GDS merge and the schema.org
reader, and only when all three found nothing; before the LLM. On the 372-mail
corpus it found 113 flights to the rules' 192, agreed on 87 and added 3 (all
without times, which the plausibility gate refuses) — the corpus is one
traveller's mail, already covered by rules, so that measures overlap rather
than what it adds for someone else's airlines.

**How it runs.** As a subprocess on the email's raw bytes, ``kitinerary-
extractor`` reading stdin and printing JSON-LD. The Docker image ships KDE's
static x86_64 build in ``/opt/kitinerary`` (~35 MB; the distro package pulled
in ~600 MB of Qt). ``settings.KITINERARY_EXTRACTOR`` points at it; empty, or a
path with no executable, switches the tier off and every call returns ``[]``.

**What is trusted.** Its JSON-LD goes through ``schema_org.flights_from_items``
— the conversion the email markup uses — so the same refusals apply: no IATA
code, no clock time, a cancelled reservation or a malformed number means no
leg. Times carry their offset, so legs come back in UTC and flagged
``_times_already_utc``; ``validate_flights`` still judges them like any other.

Never fatal: a missing binary, a timeout, a crash or unparseable output is
logged and yields ``[]``, so the LLM still gets its turn.
"""

import json
import logging
import os
import subprocess
from email.message import EmailMessage as MimeMessage
from email.utils import format_datetime

from ..config import settings
from .schema_org import flights_from_items

logger = logging.getLogger(__name__)

# Generous: the extractor renders PDFs, and the corpus's slowest mail took a
# few seconds natively. A hang must not stall the sync.
_TIMEOUT_SECONDS = 30


def extractor_path() -> str | None:
    """The configured kitinerary-extractor, or None when the tier is off."""
    path = (settings.KITINERARY_EXTRACTOR or "").strip()
    if path and os.path.isfile(path) and os.access(path, os.X_OK):
        return path
    return None


def available() -> bool:
    return extractor_path() is not None


def _raw_bytes(email_msg) -> bytes:
    """The email as MIME bytes: the original when the fetch kept it, otherwise
    rebuilt from the parts Partiu holds (body, HTML, PDF attachments)."""
    raw = getattr(email_msg, "raw_eml", None)
    if raw:
        return raw
    msg = MimeMessage()
    for header, value in (
        ("From", getattr(email_msg, "sender", "")),
        ("Subject", getattr(email_msg, "subject", "")),
        ("Message-ID", getattr(email_msg, "message_id", "")),
    ):
        if value:
            msg[header] = " ".join(str(value).split())
    date = getattr(email_msg, "date", None)
    if date is not None:
        try:
            msg["Date"] = format_datetime(date)
        except (TypeError, ValueError):
            pass
    msg.set_content(getattr(email_msg, "body", "") or "")
    html = getattr(email_msg, "html_body", None)
    if html:
        msg.add_alternative(html, subtype="html")
    for i, pdf in enumerate(getattr(email_msg, "pdf_attachments", None) or []):
        if isinstance(pdf, bytes):
            msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=f"{i}.pdf")
    return bytes(msg)


def _flatten_times(node):
    """KItinerary writes times as {"@type": "QDateTime", "@value": "...+01:00",
    "timezone": "..."}; the schema.org conversion reads a plain ISO string."""
    if isinstance(node, dict):
        if node.get("@type") == "QDateTime" and isinstance(node.get("@value"), str):
            return node["@value"]
        return {k: _flatten_times(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_flatten_times(v) for v in node]
    return node


def run_extractor(email_msg) -> list[dict]:
    """Raw JSON-LD objects for the email, or [] when the tier is off or fails."""
    path = extractor_path()
    if path is None:
        return []
    args = [path]
    date = getattr(email_msg, "date", None)
    if date is not None:
        # The year of a year-less date ("12NOV") is resolved against this.
        args += ["--context-date", date.isoformat()]
    try:
        result = subprocess.run(
            args,
            input=_raw_bytes(email_msg),
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
            # Qt warns and switches locale without a UTF-8 one.
            env={**os.environ, "LANG": "C.UTF-8"},
        )
    except subprocess.TimeoutExpired:
        logger.warning("kitinerary: timed out on %r", getattr(email_msg, "subject", "")[:60])
        return []
    except OSError as e:
        logger.warning("kitinerary: could not run %s: %s", path, e)
        return []
    if result.returncode != 0:
        logger.warning(
            "kitinerary: exit %d on %r", result.returncode, getattr(email_msg, "subject", "")[:60]
        )
        return []
    try:
        data = json.loads(result.stdout or b"[]")
    except ValueError:
        logger.warning("kitinerary: unparseable output")
        return []
    items = data if isinstance(data, list) else [data]
    return [_flatten_times(item) for item in items if isinstance(item, dict)]


def extract_kitinerary_flights(email_msg) -> list[dict]:
    """Flight legs KItinerary finds in the email, in the rule parsers' shape."""
    flights = flights_from_items(run_extractor(email_msg))
    if flights:
        logger.info(
            "kitinerary: %d flight(s) from %r",
            len(flights),
            getattr(email_msg, "subject", "")[:60],
        )
    return flights
