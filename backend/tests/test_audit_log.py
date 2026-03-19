"""Tests for backend.audit_log."""

import json
import logging
from pathlib import Path


class TestAuditLog:
    def test_audit_writes_json_line(self, test_db, tmp_path):
        import backend.audit_log as audit_mod

        audit_mod._audit_logger = None  # reset singleton

        from backend.audit_log import audit

        audit("login_success", user_id=1, ip="127.0.0.1")

        log_path = Path(test_db).parent / "audit.log"
        assert log_path.exists()
        lines = log_path.read_text().strip().splitlines()
        assert len(lines) >= 1
        record = json.loads(lines[-1])
        assert record["event"] == "login_success"
        assert record["user_id"] == 1
        assert record["ip"] == "127.0.0.1"
        assert "ts" in record

    def test_audit_includes_timestamp(self, test_db):
        import backend.audit_log as audit_mod

        audit_mod._audit_logger = None

        from backend.audit_log import audit

        audit("test_event")

        log_path = Path(test_db).parent / "audit.log"
        lines = log_path.read_text().strip().splitlines()
        record = json.loads(lines[-1])
        assert "ts" in record
        assert "T" in record["ts"]  # ISO format

    def test_audit_user_id_none(self, test_db):
        import backend.audit_log as audit_mod

        audit_mod._audit_logger = None

        from backend.audit_log import audit

        audit("anonymous_event")

        log_path = Path(test_db).parent / "audit.log"
        lines = log_path.read_text().strip().splitlines()
        record = json.loads(lines[-1])
        assert record["user_id"] is None

    def test_audit_extra_kwargs(self, test_db):
        import backend.audit_log as audit_mod

        audit_mod._audit_logger = None

        from backend.audit_log import audit

        audit("password_change", user_id=5, result="ok", username="alice")

        log_path = Path(test_db).parent / "audit.log"
        lines = log_path.read_text().strip().splitlines()
        record = json.loads(lines[-1])
        assert record["result"] == "ok"
        assert record["username"] == "alice"

    def test_audit_does_not_raise_on_error(self, test_db):
        """audit() must never raise, even with a bad logger."""
        import backend.audit_log as audit_mod

        bad_logger = logging.getLogger("bad")
        # Remove any handlers to ensure it can't write
        bad_logger.handlers.clear()
        audit_mod._audit_logger = bad_logger

        from backend.audit_log import audit

        # Should not raise
        audit("some_event", user_id=99)

        # cleanup
        audit_mod._audit_logger = None

    def test_audit_singleton_reused(self, test_db):
        import backend.audit_log as audit_mod

        audit_mod._audit_logger = None

        from backend.audit_log import _get_logger

        logger1 = _get_logger()
        logger2 = _get_logger()
        assert logger1 is logger2
