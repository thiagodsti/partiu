"""Shared pytest fixtures for backend tests."""

import email as stdlib_email
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# MUST be set before any backend imports so Settings picks it up.
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-minimum-32chars!")
os.environ.setdefault("BCRYPT_ROUNDS", "4")

# Add the project root so that `backend` is importable as a package.
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

# Disable rate limiting before route modules are first imported.
import backend.limiter as _limiter_mod  # noqa: E402

_noop_limiter = MagicMock()
_noop_limiter.limit = lambda *a, **kw: lambda f: f
_limiter_mod.limiter = _noop_limiter

FIXTURES_DIR = Path(__file__).parent / "fixtures"

CACHE_PATH = ROOT / "data" / "email_cache.json"
FIXTURE_CACHE_PATH = FIXTURES_DIR / "email_cache.json"


@pytest.fixture(scope="session")
def email_cache():
    """Load the email cache for parsing tests."""
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

    # Also patch the config.settings so auth.py / audit_log.py see the same path.
    import backend.config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "DB_PATH", db_path)
    monkeypatch.setattr(
        cfg_module.settings, "SECRET_KEY", "test-secret-key-for-testing-minimum-32chars!"
    )

    # Reset lazy singletons that depend on DB_PATH / SECRET_KEY.
    import backend.auth as auth_mod

    auth_mod._serializer = None

    import backend.audit_log as audit_mod

    audit_mod._audit_logger = None

    import backend.crypto as crypto_mod

    crypto_mod._fernet = None

    from backend.database import init_database

    init_database()

    yield db_path


@pytest.fixture
def api_app(test_db):
    """Create a minimal FastAPI app with all API routers for integration testing."""
    from fastapi import FastAPI

    from backend.routes import airports as airports_routes
    from backend.routes import auth as auth_routes
    from backend.routes import boarding_passes as bp_routes
    from backend.routes import day_notes as day_notes_routes
    from backend.routes import failed_emails as failed_emails_routes
    from backend.routes import flights as flights_routes
    from backend.routes import notifications as notifications_routes
    from backend.routes import settings as settings_routes
    from backend.routes import shares as shares_routes
    from backend.routes import sync as sync_routes
    from backend.routes import trip_documents as trip_documents_routes
    from backend.routes import trips as trips_routes
    from backend.routes import users as users_routes

    app = FastAPI()
    app.include_router(auth_routes.router)
    app.include_router(users_routes.router)
    # shares router MUST be registered BEFORE trips router to avoid
    # /api/trips/invitations being matched by trips' /{trip_id} route
    app.include_router(shares_routes.router)
    app.include_router(trips_routes.router)
    app.include_router(flights_routes.router)
    app.include_router(sync_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(airports_routes.router)
    app.include_router(notifications_routes.router)
    app.include_router(bp_routes.router)
    app.include_router(failed_emails_routes.router)
    app.include_router(trip_documents_routes.router)
    app.include_router(day_notes_routes.router)
    return app


@pytest.fixture
def client(api_app):
    """Unauthenticated TestClient."""
    from fastapi.testclient import TestClient

    with TestClient(api_app, raise_server_exceptions=True, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def auth_client(api_app):
    """TestClient pre-logged-in as admin."""
    from fastapi.testclient import TestClient

    with TestClient(api_app, raise_server_exceptions=True, base_url="https://testserver") as c:
        r = c.post("/api/auth/setup", json={"username": "admin", "password": "password123"})
        assert r.status_code == 200, r.text
        yield c


def load_anonymized_fixture(json_filename: str):
    """
    Load an anonymized JSON fixture (produced by email_anonymizer.save_anonymized_fixture)
    into an EmailMessage for parser pipeline tests.

    Use this instead of load_eml_as_email_message() for fixtures that were created via
    the automated anonymization pipeline — these contain no real PII.
    """
    import json
    from datetime import timezone

    from backend.parsers.email_connector import EmailMessage

    data = json.loads((FIXTURES_DIR / json_filename).read_text(encoding="utf-8"))

    date_str = data.get("date")
    msg_date: datetime | None = None
    if date_str:
        try:
            msg_date = datetime.fromisoformat(date_str).replace(tzinfo=UTC)
        except ValueError:
            msg_date = datetime.now(tz=UTC)

    pdf_attachments: list[bytes] = [
        bytes(b) if isinstance(b, list) else b for b in (data.get("pdf_attachments") or [])
    ]

    return EmailMessage(
        message_id=data.get("message_id", f"test-{json_filename}"),
        sender=data.get("sender", ""),
        subject=data.get("subject", ""),
        body=data.get("body") or "",
        date=msg_date or datetime.now(tz=UTC),
        html_body=data.get("html_body") or "",
        pdf_attachments=pdf_attachments,
    )


@pytest.fixture(scope="module")
def seeded_airports_db(tmp_path_factory):
    """
    Create a temporary SQLite DB with a minimal airports table seeded.

    Parser tests that call _resolve_iata() need this; without it the airports
    table is empty in CI and all IATA lookups return "", causing parsers to
    return zero flights.
    """
    import backend.config as cfg_module
    import backend.database as db_module

    db_path = str(tmp_path_factory.mktemp("airports_db") / "test.db")
    original_path = db_module.settings.DB_PATH

    db_module.settings.DB_PATH = db_path
    cfg_module.settings.DB_PATH = db_path

    # Clear resolve_iata (and _is_valid_iata) caches so any prior empty
    # results cached without a DB don't bleed into this module's tests.
    from backend.parsers.shared import resolve_iata

    resolve_iata.cache_clear()

    from backend.database import db_write, init_database

    init_database()

    airports = [
        ("ARN", "Stockholm Arlanda Airport", "Stockholm", "SE"),
        ("LHR", "London Heathrow Airport", "London", "GB"),
        ("GRU", "Guarulhos International Airport", "Sao Paulo", "BR"),
        ("MAD", "Madrid-Barajas Airport", "Madrid", "ES"),
        ("VIE", "Vienna International Airport", "Vienna", "AT"),
        ("FCO", "Rome Fiumicino Airport", "Rome", "IT"),
        ("CPH", "Copenhagen Airport", "Copenhagen", "DK"),
        ("OSL", "Oslo Gardermoen Airport", "Oslo", "NO"),
        ("HEL", "Helsinki-Vantaa Airport", "Helsinki", "FI"),
        ("GIG", "Rio de Janeiro Galeao Airport", "Rio de Janeiro", "BR"),
        ("VCP", "Campinas Viracopos Airport", "Campinas", "BR"),
        ("GRU", "Sao Paulo Guarulhos International Airport", "Sao Paulo", "BR"),
    ]
    with db_write() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO airports (iata_code, name, city_name, country_code)"
            " VALUES (?, ?, ?, ?)",
            airports,
        )

    yield db_path

    db_module.settings.DB_PATH = original_path
    cfg_module.settings.DB_PATH = original_path
    # Clear again so stale "valid" results don't bleed into later modules.
    resolve_iata.cache_clear()


def load_eml_as_email_message(eml_filename: str):
    """Parse a .eml fixture file into an EmailMessage for parser pipeline tests."""
    from backend.parsers.email_connector import EmailMessage, decode_header_value

    raw = (FIXTURES_DIR / eml_filename).read_bytes()
    msg = stdlib_email.message_from_bytes(raw)

    body = ""
    html_body = ""
    pdf_attachments: list[bytes] = []

    for part in msg.walk():
        ct = part.get_content_type()
        if ct == "text/plain" and not body:
            raw = part.get_payload(decode=True)
            body = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else ""
        elif ct == "text/html" and not html_body:
            raw = part.get_payload(decode=True)
            html_body = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else ""
        elif ct == "application/pdf":
            raw = part.get_payload(decode=True)
            if isinstance(raw, bytes):
                pdf_attachments.append(raw)

    return EmailMessage(
        message_id=f"test-{eml_filename}",
        sender=decode_header_value(msg.get("From") or ""),
        subject=decode_header_value(msg.get("Subject") or ""),
        body=body,
        date=datetime.now(tz=UTC),
        html_body=html_body,
        pdf_attachments=pdf_attachments,
    )
