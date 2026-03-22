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
    from backend.routes import failed_emails as failed_emails_routes
    from backend.routes import flights as flights_routes
    from backend.routes import notifications as notifications_routes
    from backend.routes import settings as settings_routes
    from backend.routes import sync as sync_routes
    from backend.routes import trips as trips_routes
    from backend.routes import users as users_routes

    app = FastAPI()
    app.include_router(auth_routes.router)
    app.include_router(users_routes.router)
    app.include_router(trips_routes.router)
    app.include_router(flights_routes.router)
    app.include_router(sync_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(airports_routes.router)
    app.include_router(notifications_routes.router)
    app.include_router(bp_routes.router)
    app.include_router(failed_emails_routes.router)
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


def load_eml_as_email_message(eml_filename: str):
    """Parse a .eml fixture file into an EmailMessage for parser pipeline tests."""
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
        date=datetime.now(tz=UTC),
        html_body=html_body,
        pdf_attachments=pdf_attachments,
    )
