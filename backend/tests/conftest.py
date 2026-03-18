"""Shared pytest fixtures for backend tests."""
import email as stdlib_email
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Add the project root so that `backend` is importable as a package.
# This lets modules that use relative imports (e.g. database.py) work correctly.
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES_DIR = Path(__file__).parent / "fixtures"

CACHE_PATH = ROOT / "data" / "email_cache.json"
FIXTURE_CACHE_PATH = FIXTURES_DIR / "email_cache.json"


@pytest.fixture(scope="session")
def email_cache():
    """Load the email cache for parsing tests.

    Priority:
      1. data/email_cache.json  — real emails from a local sync (gitignored)
      2. backend/tests/fixtures/email_cache.json — anonymized fixture (committed)
    """
    path = CACHE_PATH if CACHE_PATH.exists() else FIXTURE_CACHE_PATH
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Initialise a temporary SQLite DB with the full schema and patch DB_PATH."""
    db_path = str(tmp_path / "test.db")

    import backend.database as db_module
    monkeypatch.setattr(db_module.settings, "DB_PATH", db_path)

    from backend.database import init_database
    init_database()

    yield db_path


def load_eml_as_email_message(eml_filename: str):
    """
    Parse a .eml fixture file and return an EmailMessage ready for the parser
    pipeline.  Extracts text/plain, text/html and PDF attachments.
    """
    from backend.parsers.email_connector import EmailMessage

    raw = (FIXTURES_DIR / eml_filename).read_bytes()
    msg = stdlib_email.message_from_bytes(raw)

    body = ""
    html_body = ""
    pdf_attachments: list[bytes] = []

    for part in msg.walk():
        ct = part.get_content_type()
        if ct == "text/plain" and not body:
            body = part.get_payload(decode=True).decode("utf-8", errors="replace")
        elif ct == "text/html" and not html_body:
            html_body = part.get_payload(decode=True).decode("utf-8", errors="replace")
        elif ct == "application/pdf":
            pdf_attachments.append(part.get_payload(decode=True))

    return EmailMessage(
        message_id=f"test-{eml_filename}",
        sender=msg["From"] or "",
        subject=msg["Subject"] or "",
        body=body,
        date=datetime.now(tz=timezone.utc),
        html_body=html_body,
        pdf_attachments=pdf_attachments,
    )
