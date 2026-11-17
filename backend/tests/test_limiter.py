"""The limiter's test-server switch: on by default, off only when asked."""

import importlib
import logging

import pytest

import backend.limiter as limiter_mod


@pytest.fixture
def reload_limiter(monkeypatch):
    """Rebuild the module's limiter under a given setting, then put conftest's no-op back."""
    from backend.config import settings

    original = limiter_mod.limiter

    def _reload(disabled: bool):
        monkeypatch.setattr(settings, "DISABLE_RATE_LIMITS", disabled)
        return importlib.reload(limiter_mod).limiter

    yield _reload
    limiter_mod.limiter = original


class TestDisableRateLimits:
    def test_limits_are_enforced_by_default(self, reload_limiter):
        assert reload_limiter(False).enabled is True

    def test_the_switch_turns_them_off_and_says_so(self, reload_limiter, caplog):
        with caplog.at_level(logging.WARNING, logger="backend.limiter"):
            assert reload_limiter(True).enabled is False
        assert "DISABLE_RATE_LIMITS" in caplog.text
