"""
SQLite database schema initialization and connection helpers.
Uses WAL journal mode for concurrent reads during background sync.
"""

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from .config import settings

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()


def get_db_path() -> str:
    return settings.DB_PATH


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with WAL mode and row_factory set."""
    path = db_path or get_db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def db_conn():
    """Context manager yielding a read-only-style connection (auto-close)."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def db_write():
    """Context manager yielding a connection with the write lock held."""
    with _write_lock:
        conn = get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Global settings helpers
# ---------------------------------------------------------------------------


def get_global_setting(key: str, default: str = "") -> str:
    """Read a single value from the global_settings table."""
    try:
        with db_conn() as conn:
            row = conn.execute("SELECT value FROM global_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default
    except Exception:
        return default


def set_global_setting(key: str, value: str):
    """Upsert a value in the global_settings table."""
    with db_write() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO global_settings (key, value) VALUES (?, ?)", (key, value)
        )


# ---------------------------------------------------------------------------
# Migrations are managed by Alembic (see /alembic/). The pre-Alembic migration
# history (versions 1-26) is preserved in git history and fully captured by
# alembic/versions/0001_baseline_schema.py, the schema snapshot at adoption time.
# ---------------------------------------------------------------------------


def _get_alembic_config():
    from alembic.config import Config

    project_root = Path(__file__).parent.parent
    # Don't rely on alembic.ini for programmatic use — set everything explicitly.
    # alembic.ini is only needed for CLI commands (alembic revision, alembic history, etc.)
    cfg = Config()
    cfg.set_main_option("script_location", str(project_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{get_db_path()}")
    return cfg


def _run_alembic_migrations():
    """Apply pending Alembic migrations.

    For databases that still carry a PRAGMA user_version from the old custom
    migration system, we stamp them at the Alembic baseline revision instead of
    re-running all the SQL — the schema is already there.
    """
    from alembic import command

    cfg = _get_alembic_config()

    conn = get_connection()
    try:
        old_version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()

    if old_version > 0:
        logger.info(
            "Legacy DB detected (PRAGMA user_version=%d) — stamping Alembic baseline then upgrading",
            old_version,
        )
        # Stamp at 0001 (baseline) so Alembic knows the old schema is already in place,
        # then upgrade to head to apply any new migrations (0002, etc.).
        command.stamp(cfg, "0001")
        with db_write() as c:
            c.execute("PRAGMA user_version = 0")
        command.upgrade(cfg, "head")
    else:
        command.upgrade(cfg, "head")


def _encrypt_existing_credentials() -> None:
    """One-time migration: encrypt any plaintext credentials in the users table."""
    if get_global_setting("credentials_encrypted") == "true":
        return

    from .crypto import encrypt, is_encrypted
    from .users.repository import UserRepository

    repository = UserRepository()
    for user in repository.list_credential_columns():
        updates: dict = {}
        pwd = user["gmail_app_password"]
        if pwd and not is_encrypted(pwd):
            updates["gmail_app_password"] = encrypt(pwd)
        key = user["immich_api_key"]
        if key and not is_encrypted(key):
            updates["immich_api_key"] = encrypt(key)
        if updates:
            repository.update_user(user["id"], updates)

    set_global_setting("credentials_encrypted", "true")
    logger.info("Credential encryption migration complete")


def init_database():
    """Run pending Alembic migrations then seed static data."""
    from .integrations.aircraft.repository import AircraftTypeRepository

    logger.info("Initializing database at %s", get_db_path())
    _run_alembic_migrations()
    _encrypt_existing_credentials()
    _migrate_legacy_encryption()
    AircraftTypeRepository().normalize_existing_flight_types()
    AircraftTypeRepository().seed_if_empty()
    logger.info("Database ready")


def _migrate_legacy_encryption() -> None:
    """Re-encrypt any credentials still using the old SHA-256 key (runs once)."""
    if get_global_setting("crypto_pbkdf2_migrated") == "1":
        return
    from .crypto import migrate_legacy_encryption

    count = migrate_legacy_encryption()
    if count:
        logger.info("Re-encrypted %d credential(s) to PBKDF2 key", count)
    set_global_setting("crypto_pbkdf2_migrated", "1")
