"""Tests for the optional-integration status report.

The two invariants worth guarding: no key value ever leaves the server, and
Photon is reported with three states rather than a set/unset boolean.
"""

from unittest.mock import patch

import bcrypt
from fastapi.testclient import TestClient

from backend.settings.integrations import PUBLIC_PHOTON_URL, integration_statuses


def _by_key(statuses):
    return {s.key: s for s in statuses}


class TestStatuses:
    def test_reports_every_optional_integration(self):
        assert set(_by_key(integration_statuses())) == {
            "carto",
            "aviationstack",
            "photon",
            "ollama",
            "push",
        }

    def test_an_unset_key_is_reported_with_its_env_var(self):
        from backend.settings import integrations

        with patch.object(integrations.settings, "CARTO_API_KEY", ""):
            carto = _by_key(integration_statuses())["carto"]

        assert carto.configured is False
        assert carto.state == "unset"
        assert carto.env_var == "CARTO_API_KEY"

    def test_a_set_key_is_reported_as_configured(self):
        from backend.settings import integrations

        with patch.object(integrations.settings, "AVIATIONSTACK_API_KEY", "secret-value"):
            aviationstack = _by_key(integration_statuses())["aviationstack"]

        assert aviationstack.configured is True
        assert aviationstack.state == "set"

    def test_no_key_value_is_ever_exposed(self):
        """The whole point of reporting `configured` rather than the value."""
        from backend.settings import integrations

        secret = "super-secret-key-value"
        with (
            patch.object(integrations.settings, "CARTO_API_KEY", secret),
            patch.object(integrations.settings, "AVIATIONSTACK_API_KEY", secret),
            patch.object(integrations.settings, "VAPID_PRIVATE_KEY", secret),
        ):
            rendered = repr(integration_statuses())

        assert secret not in rendered

    def test_push_offers_no_env_var_because_the_ui_generates_it(self):
        """Telling an admin to hand-edit VAPID_PRIVATE_KEY would be worse advice
        than the generate button that already exists."""
        assert _by_key(integration_statuses())["push"].env_var is None


class TestPhotonStates:
    """Photon defaults to a public instance, so a set/unset boolean would claim
    credit for something the admin never chose."""

    def test_the_default_is_reported_as_the_public_instance(self):
        from backend.settings import integrations

        with patch.object(integrations.settings, "PHOTON_URL", PUBLIC_PHOTON_URL):
            photon = _by_key(integration_statuses())["photon"]

        assert photon.configured is True
        assert photon.state == "public_instance"

    def test_a_trailing_slash_is_still_the_public_instance(self):
        from backend.settings import integrations

        with patch.object(integrations.settings, "PHOTON_URL", PUBLIC_PHOTON_URL + "/"):
            assert _by_key(integration_statuses())["photon"].state == "public_instance"

    def test_another_url_is_self_hosted(self):
        from backend.settings import integrations

        with patch.object(integrations.settings, "PHOTON_URL", "http://photon.internal:2322"):
            photon = _by_key(integration_statuses())["photon"]

        assert photon.configured is True
        assert photon.state == "self_hosted"

    def test_an_empty_url_is_disabled_not_merely_unset(self):
        from backend.settings import integrations

        with patch.object(integrations.settings, "PHOTON_URL", ""):
            photon = _by_key(integration_statuses())["photon"]

        assert photon.configured is False
        assert photon.state == "disabled"


class TestStartupLog:
    def test_the_summary_is_info_not_a_warning(self, caplog):
        """These are optional; warning about a deliberate configuration is how
        people learn to ignore warnings."""
        import logging

        from backend.settings.integrations import log_integration_summary

        with caplog.at_level(logging.INFO, logger="backend.settings.integrations"):
            log_integration_summary()

        records = [r for r in caplog.records if "Optional integrations" in r.message]
        assert records
        assert all(r.levelno == logging.INFO for r in records)

    def test_the_summary_names_what_is_missing(self, caplog):
        import logging

        from backend.settings import integrations

        with (
            patch.object(integrations.settings, "CARTO_API_KEY", ""),
            patch.object(integrations.settings, "AVIATIONSTACK_API_KEY", "x"),
            caplog.at_level(logging.INFO, logger="backend.settings.integrations"),
        ):
            integrations.log_integration_summary()

        text = " ".join(r.getMessage() for r in caplog.records)
        assert "carto" in text
        assert "not configured" in text

    def test_the_summary_never_contains_a_key(self, caplog):
        import logging

        from backend.settings import integrations

        secret = "super-secret-key-value"
        with (
            patch.object(integrations.settings, "CARTO_API_KEY", secret),
            caplog.at_level(logging.INFO, logger="backend.settings.integrations"),
        ):
            integrations.log_integration_summary()

        assert secret not in " ".join(r.getMessage() for r in caplog.records)


class TestEndpoint:
    def test_admin_gets_the_status_list(self, auth_client):
        r = auth_client.get("/api/settings/admin/integrations")
        assert r.status_code == 200
        keys = {row["key"] for row in r.json()}
        assert {"carto", "aviationstack", "photon", "ollama", "push"} == keys

    def test_the_response_carries_no_key_material(self, auth_client):
        from backend.settings import integrations

        secret = "super-secret-key-value"
        with patch.object(integrations.settings, "CARTO_API_KEY", secret):
            body = auth_client.get("/api/settings/admin/integrations").text

        assert secret not in body

    def test_unauthenticated_is_refused(self, client):
        assert client.get("/api/settings/admin/integrations").status_code == 401

    def test_a_non_admin_is_refused(self, api_app, auth_client):
        """Every one of these is a server-level setting, so a regular user can
        do nothing with the answer."""
        from backend.database import db_write

        with db_write() as conn:
            ph = bcrypt.hashpw(b"pass1234", bcrypt.gensalt()).decode()
            conn.execute(
                "INSERT OR IGNORE INTO users (username, password_hash, is_admin) VALUES (?, ?, 0)",
                ("integ_regular", ph),
            )
        c = TestClient(api_app, raise_server_exceptions=True, base_url="https://testserver")
        assert (
            c.post(
                "/api/auth/login", json={"username": "integ_regular", "password": "pass1234"}
            ).status_code
            == 200
        )

        assert c.get("/api/settings/admin/integrations").status_code == 403
