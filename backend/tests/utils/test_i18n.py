"""Tests for backend.utils.i18n (t())."""


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
