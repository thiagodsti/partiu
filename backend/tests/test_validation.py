"""Tests for backend.validation (shared SSRF-prevention validators)."""

import pytest


class TestValidateExternalHost:
    def test_rejects_empty(self):
        from backend.validation import validate_external_host

        with pytest.raises(ValueError, match="cannot be empty"):
            validate_external_host("", "IMAP host")

    def test_rejects_localhost(self):
        from backend.validation import validate_external_host

        with pytest.raises(ValueError, match="local address"):
            validate_external_host("localhost", "IMAP host")

    def test_rejects_loopback_ip(self):
        from backend.validation import validate_external_host

        with pytest.raises(ValueError, match="private or local address"):
            validate_external_host("127.0.0.1", "IMAP host")

    def test_rejects_private_ip(self):
        from backend.validation import validate_external_host

        with pytest.raises(ValueError, match="private or local address"):
            validate_external_host("192.168.1.1", "IMAP host")

    def test_allows_public_host(self):
        from backend.validation import validate_external_host

        validate_external_host("imap.gmail.com", "IMAP host")  # should not raise

    def test_message_uses_field_name(self):
        from backend.validation import validate_external_host

        with pytest.raises(ValueError, match="^Custom field cannot be empty$"):
            validate_external_host("", "Custom field")


class TestValidateExternalUrl:
    def test_empty_returns_empty(self):
        from backend.validation import validate_external_url

        assert validate_external_url("", "Immich URL") == ""

    def test_rejects_non_http_scheme(self):
        from backend.validation import validate_external_url

        with pytest.raises(ValueError, match="must use http or https"):
            validate_external_url("ftp://example.com", "Immich URL")

    def test_rejects_missing_hostname(self):
        from backend.validation import validate_external_url

        with pytest.raises(ValueError, match="missing a hostname"):
            validate_external_url("http://", "Immich URL")

    def test_rejects_localhost(self):
        from backend.validation import validate_external_url

        with pytest.raises(ValueError, match="local address"):
            validate_external_url("http://localhost:2283", "Immich URL")

    def test_rejects_private_ip(self):
        from backend.validation import validate_external_url

        with pytest.raises(ValueError, match="private or local address"):
            validate_external_url("http://10.0.0.5:2283", "Immich URL")

    def test_allows_public_url(self):
        from backend.validation import validate_external_url

        assert validate_external_url("https://immich.example.com", "Immich URL") == (
            "https://immich.example.com"
        )
