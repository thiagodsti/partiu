"""Tests for backend.utils.i18n (t())."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def clean_cache():
    """Drop the module-level locale cache around a test."""
    from backend.utils import i18n

    saved = dict(i18n._cache)
    i18n._cache.clear()
    yield i18n
    i18n._cache.clear()
    i18n._cache.update(saved)


class TestTranslate:
    def test_returns_english_by_default(self):
        from backend.utils.i18n import t

        assert t("nav.trips") == "Trips"

    def test_returns_translated_locale(self):
        from backend.utils.i18n import t

        assert t("nav.trips", "pt-BR") == "Viagens"

    def test_unsupported_locale_falls_back_to_english(self):
        from backend.utils.i18n import t

        assert t("nav.trips", "fr") == "Trips"

    def test_unknown_key_returns_key_itself(self):
        from backend.utils.i18n import t

        assert t("not.a.real.key") == "not.a.real.key"

    def test_formats_placeholders(self):
        from backend.utils.i18n import t

        result = t("notif.flight_reminder_title", "en", flight="LA8094", mins=45)
        assert result == "Flight LA8094 in ~45 min"

    def test_formats_placeholders_in_other_locale(self):
        from backend.utils.i18n import t

        result = t("notif.flight_reminder_title", "pt-BR", flight="LA8094", mins=45)
        assert result == "Voo LA8094 em ~45 min"

    def test_missing_placeholder_returns_unformatted_template(self):
        from backend.utils.i18n import t

        # Should not raise even if a required placeholder is missing.
        result = t("notif.flight_reminder_title", "en")
        assert "{flight}" in result


class TestLocaleFileResolution:
    """The deployed image ships locales outside frontend/src — see Dockerfile."""

    def test_falls_back_to_backend_locales_dir(self, clean_cache, tmp_path):
        i18n = clean_cache
        (tmp_path / "backend" / "locales").mkdir(parents=True)
        (tmp_path / "backend" / "locales" / "en.json").write_text(
            json.dumps({"notif.test_title": "From backend/locales"}), encoding="utf-8"
        )

        # No frontend/src/locales here, mirroring the built image.
        with patch.object(i18n, "_ROOT", tmp_path):
            assert i18n.t("notif.test_title") == "From backend/locales"

    def test_locales_dir_env_var_wins(self, clean_cache, tmp_path):
        i18n = clean_cache
        (tmp_path / "en.json").write_text(
            json.dumps({"notif.test_title": "From env dir"}), encoding="utf-8"
        )

        with patch.dict("os.environ", {"LOCALES_DIR": str(tmp_path)}):
            assert i18n.t("notif.test_title") == "From env dir"

    def test_returns_key_when_no_locale_file_anywhere(self, clean_cache, tmp_path):
        i18n = clean_cache

        with patch.object(i18n, "_ROOT", tmp_path):
            assert i18n.t("notif.test_title") == "notif.test_title"

    def test_repo_checkout_resolves_frontend_locales(self, clean_cache):
        """Guards the default path that the repo (non-Docker) run relies on."""
        i18n = clean_cache
        frontend_dir = i18n._ROOT / "frontend" / "src" / "locales"

        assert frontend_dir in i18n._candidate_dirs()
        assert (frontend_dir / "en.json").is_file()
        assert Path(i18n._ROOT / "backend" / "locales") in i18n._candidate_dirs()
