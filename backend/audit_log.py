"""
Structured audit logging for security-sensitive operations.
Writes JSON lines to a rotating file (overwrite on full).
"""

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .utils import now_iso

_audit_logger: logging.Logger | None = None


def _get_logger() -> logging.Logger:
    global _audit_logger
    if _audit_logger is None:
        from .config import settings

        _audit_logger = logging.getLogger("partiu.audit")
        _audit_logger.setLevel(logging.INFO)
        _audit_logger.propagate = False

        log_path = Path(settings.DB_PATH).parent / "audit.log"
        max_bytes = settings.AUDIT_LOG_MAX_MB * 1024 * 1024
        handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        _audit_logger.addHandler(handler)

    return _audit_logger


def audit(event: str, user_id: int | None = None, **kwargs) -> None:
    """Emit a structured audit log entry."""
    record = {
        "ts": now_iso(),
        "event": event,
        "user_id": user_id,
        **kwargs,
    }
    try:
        _get_logger().info(json.dumps(record, default=str))
    except Exception:
        pass  # never let audit logging crash the application
