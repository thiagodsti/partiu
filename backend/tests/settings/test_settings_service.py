"""Tests for backend.settings.service (validation, SSRF checks, global-settings gating)."""

import itertools
from datetime import UTC, datetime

import pytest

_user_counter = itertools.count(1)


def _seed_user(db_path: str, is_admin: bool = False) -> dict:
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    username = f"testuser{next(_user_counter)}"
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
        (username, "hashed", int(is_admin), datetime.now(UTC).isoformat()),
    )
    conn.commit()
    user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row)


class TestGetSettings:
    def test_defaults_for_new_user(self, test_db):
        from backend.settings.service import SettingsService

        service = SettingsService()
        user = _seed_user(test_db)

        settings = service.get_settings(user)
        assert settings.imap_host == "imap.gmail.com"
        assert settings.imap_port == 993
        assert settings.default_currency == "EUR"
        assert settings.smtp_server_port is None

    def test_admin_gets_smtp_server_port(self, test_db):
        from backend.settings.service import SettingsService

        service = SettingsService()
        user = _seed_user(test_db, is_admin=True)

        settings = service.get_settings(user)
        assert settings.smtp_server_port == 2525


class TestUpdateSettingsValidation:
    def test_rejects_invalid_imap_port(self, test_db):
        from backend.settings.service import SettingsService, ValidationError

        service = SettingsService()
        user = _seed_user(test_db)
        with pytest.raises(ValidationError):
            service.update_settings(user, {"imap_port": 99999})

    def test_rejects_localhost_imap_host(self, test_db):
        from backend.settings.service import SettingsService, ValidationError

        service = SettingsService()
        user = _seed_user(test_db)
        with pytest.raises(ValidationError):
            service.update_settings(user, {"imap_host": "localhost"})

    def test_rejects_localhost_immich_url(self, test_db):
        from backend.settings.service import SettingsService, ValidationError

        service = SettingsService()
        user = _seed_user(test_db)
        with pytest.raises(ValidationError):
            service.update_settings(user, {"immich_url": "http://localhost:2283"})

    def test_rejects_unsupported_currency(self, test_db):
        from backend.settings.service import SettingsService, ValidationError

        service = SettingsService()
        user = _seed_user(test_db)
        with pytest.raises(ValidationError):
            service.update_settings(user, {"default_currency": "XYZ"})

    def test_global_settings_require_admin(self, test_db):
        from backend.settings.service import AdminRequiredError, SettingsService

        service = SettingsService()
        user = _seed_user(test_db, is_admin=False)
        with pytest.raises(AdminRequiredError):
            service.update_settings(user, {"sync_interval_minutes": 20})

    def test_admin_can_update_global_settings(self, test_db):
        from backend.settings.service import SettingsService

        service = SettingsService()
        user = _seed_user(test_db, is_admin=True)
        service.update_settings(user, {"sync_interval_minutes": 20})

        assert service.get_settings(user).sync_interval_minutes == 20

    def test_sync_interval_out_of_range_rejected(self, test_db):
        from backend.settings.service import SettingsService, ValidationError

        service = SettingsService()
        user = _seed_user(test_db, is_admin=True)
        with pytest.raises(ValidationError):
            service.update_settings(user, {"sync_interval_minutes": 5000})

    def test_smtp_conflict_detected(self, test_db):
        from backend.settings.service import SettingsService, SmtpConflictError

        service = SettingsService()
        owner = _seed_user(test_db)
        other = _seed_user(test_db)
        service.update_settings(owner, {"smtp_recipient_address": "shared@example.com"})

        with pytest.raises(SmtpConflictError):
            service.update_settings(other, {"smtp_recipient_address": "shared@example.com"})

    def test_smtp_recipient_auto_filled_from_domain_when_blank(self, test_db):
        import sqlite3

        from backend.settings.service import SettingsService

        service = SettingsService()
        service._repository.set_global_setting("smtp_domain", "mail.example.com")
        user = _seed_user(test_db)

        service.update_settings(user, {"smtp_recipient_address": ""})

        # get_settings reads per-user fields from the passed-in dict (no re-query, by
        # design — matches get_current_user's already-loaded row), so re-fetch here.
        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        refreshed = dict(conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone())
        conn.close()

        settings = service.get_settings(refreshed)
        assert settings.smtp_recipient_address == f"{user['username']}@mail.example.com"

    def test_gmail_password_is_encrypted_at_rest(self, test_db):
        import sqlite3

        from backend.settings.service import SettingsService

        service = SettingsService()
        user = _seed_user(test_db)
        service.update_settings(user, {"gmail_app_password": "supersecret"})

        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT gmail_app_password FROM users WHERE id = ?", (user["id"],)
        ).fetchone()
        conn.close()
        assert row["gmail_app_password"] != "supersecret"


class TestTestImap:
    def test_requires_address(self, test_db):
        from backend.settings.service import SettingsService, ValidationError

        service = SettingsService()
        user = _seed_user(test_db)
        with pytest.raises(ValidationError):
            service.test_imap(user, None, None, None, None)

    def test_requires_password(self, test_db):
        from backend.settings.service import SettingsService, ValidationError

        service = SettingsService()
        user = _seed_user(test_db)
        with pytest.raises(ValidationError):
            service.test_imap(user, None, None, "me@gmail.com", None)

    def test_rejects_localhost_host(self, test_db):
        from backend.settings.service import SettingsService, ValidationError

        service = SettingsService()
        user = _seed_user(test_db)
        with pytest.raises(ValidationError):
            service.test_imap(user, "localhost", 993, "me@gmail.com", "secret")


class TestNonFlightDomains:
    def test_add_list_remove_round_trip(self, test_db):
        from backend.settings.service import SettingsService

        service = SettingsService()
        normalized = service.add_non_flight_domain("  Example.com  ", "test note")
        assert normalized == "example.com"

        domains = service.list_non_flight_domains()
        assert any(d.domain == "example.com" for d in domains)

        service.remove_non_flight_domain("example.com")
        domains_after = service.list_non_flight_domains()
        assert not any(d.domain == "example.com" for d in domains_after)


class TestAirports:
    def test_get_airport_count(self, test_db):
        from backend.settings.service import SettingsService

        service = SettingsService()
        assert service.get_airport_count() == 0
