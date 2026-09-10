"""
Test: no personal data in the committed email fixtures.

Every fixture is a real airline email, so each one has to be scrubbed before it
is committed. An earlier pass only rewrote the HTML/text bodies, which left real
passenger names, two dates of birth, ticket numbers and a frequent-flyer number
sitting in the *PDF attachments* — plus a surname inside an RFC2047-encoded
Subject, where no plain-text search could see it.

These checks therefore look everywhere a fixture can hide a string: decoded
headers, every MIME part, the JSON fields, and the extracted text of every PDF.
They are deliberately structural rather than a list of real names, so a fixture
carrying someone else's data fails too. They are a tripwire for the shapes these
documents actually use — a name after a title or a "passenger" label, a
non-documentation address, a last-century date, a forwarding mailbox's
message-id — not a proof of anonymity: a bare name in a PDF column with no label
in front of it would still get through, so a new fixture still needs reading.
"""

import base64
import email as stdlib_email
import io
import json
import re
from email.header import decode_header, make_header
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# Addresses a fixture may contain: the documentation domains, and the airlines'
# and their ESPs' own machine addresses.
ALLOWED_EMAIL_DOMAINS = (
    "example.com",
    "example.invalid",
    "example.org",
    "test.local",
    "xt.local",
    "15below.com",
    "amadeus.com",
    "mail.gmail.com",  # only ever as a DKIM/ARC domain, never a person — see below
)
ALLOWED_AIRLINE_DOMAIN_WORDS = (
    "latam",
    "flysas",
    "sas",
    "norwegian",
    "lufthansa",
    "kiwi",
    "britishairways",
    "ba.com",
    "ita-airways",
    "ryanair",
    "austrian",
    "flytap",
    "tap",
    "finnair",
    "wizzair",
    "wizz",
    "voeazul",
    "azul",
    "brusselsairlines",
    "swiss.com",
    "iberia",
    "vueling",
    "turkishairlines",
    "thy.com",
    "flypgs",
    "pegasus",
    "google.com",
    "sendgrid",
    "media-carrier.de",
)

# Names in these fixtures are the personas the scrub introduced. A real name
# reaching a fixture shows up as a word that is not in this set.
ALLOWED_NAME_WORDS = {
    "test",
    "tester",
    "testor",
    "testname",
    "testpax",
    "testtwo",
    # Personas introduced by the earlier anonymisation passes.
    "testpassenger",
    "testmr",
    "testfirst",
    "testlast",
    "passenger",
    "pax",
    "one",
    "two",
    "bob",
    "alice",
    "traveler",
    "traveller",
    "other",
    "john",
    "jane",
    "doe",
    "smith",
    "da",
    "de",
    "van",
    "adult",
    "and",
    "mr",
    "mrs",
    "ms",
}

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")
# "logo@2x.png" — retina asset names look like addresses but are filenames.
_ASSET_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
# "Mr. EDIZ TEKOK" / "Ms. Bárbara Kógus" — how these documents print passengers —
# and the labelled form an e-ticket puts in its subject line ("For passenger X").
_TITLED_NAME_RE = re.compile(
    r"\b(?:Mr|Mrs|Ms|Miss|Sr|Sra|Herr|Frau|[Ff]or\s+passenger|Passageiro\s*/\s*Passenger)"
    r"[.:]?\s+"
    r"([^\W\d_][^\W\d_]{1,20}(?:[ \t]+[^\W\d_][^\W\d_]{1,20}){1,3})"
)
# A full date with a last-century year: a birth date. Travel dates in these
# fixtures are all 2024 or later.
_BIRTH_DATE_RE = re.compile(r"\b\d{1,2}[\s./-]+(?:[^\W\d_]{3,10}\.?|\d{1,2})[\s./-]+19\d{2}\b")
# Except the treaty dates every conditions-of-carriage text cites.
CONVENTION_DATES = {"28 May 1999", "9 May 1980", "3 June 1999", "12 October 1929"}
# Message-ids of the mailbox that forwarded a mail identify its owner.
_GMAIL_MESSAGE_ID_RE = re.compile(r"<[^>]*@mail\.gmail\.com>")


def _pdf_text(data: bytes) -> str:
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception:
        return ""  # a fixture carries a truncated PDF stub on purpose


def _decode_header(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _fixture_texts(path: Path) -> list[tuple[str, str]]:
    """Every readable string in a fixture, labelled by where it came from."""
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        texts = [(f"json:{k}", v) for k, v in data.items() if isinstance(v, str) and v]
        for i, blob in enumerate(data.get("pdf_attachments") or []):
            raw = bytes(blob) if isinstance(blob, list) else base64.b64decode(blob)
            texts.append((f"json:pdf{i}", _pdf_text(raw)))
        return texts

    msg = stdlib_email.message_from_bytes(path.read_bytes())
    texts: list[tuple[str, str]] = []
    for i, part in enumerate(msg.walk()):
        for header, value in part.items():
            texts.append((f"part{i}:{header}", _decode_header(value)))
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes) or not payload:
            continue
        if part.get_content_type() == "application/pdf":
            texts.append((f"part{i}:pdf", _pdf_text(payload)))
        elif part.get_content_type().startswith("text/"):
            charset = part.get_content_charset() or "utf-8"
            texts.append((f"part{i}:body", payload.decode(charset, "replace")))
    return texts


FIXTURE_FILES = sorted(p for p in FIXTURES.iterdir() if p.suffix in (".eml", ".json"))


@pytest.fixture(scope="module")
def fixture_texts() -> dict[str, list[tuple[str, str]]]:
    return {p.name: _fixture_texts(p) for p in FIXTURE_FILES}


def test_fixtures_exist():
    assert FIXTURE_FILES, "no email fixtures found"


class TestNoEmailAddresses:
    def test_only_documentation_or_airline_addresses(self, fixture_texts):
        leaked = []
        for name, texts in fixture_texts.items():
            for label, text in texts:
                for addr in _EMAIL_RE.findall(text):
                    domain = addr.split("@", 1)[1].lower()
                    if domain.endswith(_ASSET_SUFFIXES):
                        continue
                    if domain.endswith(ALLOWED_EMAIL_DOMAINS):
                        continue
                    if any(word in domain for word in ALLOWED_AIRLINE_DOMAIN_WORDS):
                        continue
                    leaked.append(f"{name} [{label}] {addr}")
        assert not leaked, "personal email addresses in fixtures: " + "; ".join(leaked[:10])


class TestNoRealNames:
    def test_titled_names_are_test_personas(self, fixture_texts):
        """A passenger name is printed after a title in every one of these formats."""
        leaked = []
        for name, texts in fixture_texts.items():
            for label, text in texts:
                for match in _TITLED_NAME_RE.findall(text):
                    words = [w.lower() for w in match.split()][:2]
                    if len(words) == 2 and words[1] in {"da", "de", "van", "von"}:
                        words = [w.lower() for w in match.split()][:3]
                    unknown = [w for w in words if w not in ALLOWED_NAME_WORDS]
                    if unknown:
                        leaked.append(f"{name} [{label}] {match!r}")
        assert not leaked, "real names in fixtures: " + "; ".join(sorted(set(leaked))[:10])


class TestNoBirthDates:
    def test_no_last_century_dates(self, fixture_texts):
        """Travel dates here are 2024+; a 19xx date is a date of birth."""
        leaked = []
        for name, texts in fixture_texts.items():
            for label, text in texts:
                for match in _BIRTH_DATE_RE.findall(text):
                    if match.strip() in CONVENTION_DATES:
                        continue
                    leaked.append(f"{name} [{label}] {match!r}")
        assert not leaked, "possible birth dates in fixtures: " + "; ".join(leaked[:10])


class TestNoForwarderMessageIds:
    def test_no_gmail_message_ids(self, fixture_texts):
        """The forwarding mailbox's own message-id identifies its owner."""
        leaked = []
        for name, texts in fixture_texts.items():
            for label, text in texts:
                if not label.endswith(("Message-ID", "References", "In-Reply-To")):
                    continue
                if _GMAIL_MESSAGE_ID_RE.search(text) or "@mail.gmail.com" in text:
                    leaked.append(f"{name} [{label}] {text[:60]}")
        assert not leaked, "forwarder message-ids in fixtures: " + "; ".join(leaked[:10])
