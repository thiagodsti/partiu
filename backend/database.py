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
# Versioned migrations
# Each entry: (version, description, [sql_statements])
# Rules:
#   - Never edit an existing migration — add a new one instead.
#   - Each statement is executed individually so a failure is easy to pinpoint.
#   - DDL changes (ALTER TABLE, CREATE INDEX, etc.) go here.
#   - Bulk data fixes can also go here when needed.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Legacy migration history — kept for reference only.
# The active migration system is Alembic (see /alembic/).
# Do NOT add new migrations here. Run: alembic revision --autogenerate -m "..."
# ---------------------------------------------------------------------------
_LEGACY_MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (
        1,
        "Initial schema",
        [
            """CREATE TABLE IF NOT EXISTS email_sync_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_synced_at TEXT,
            last_rules_version TEXT,
            status TEXT DEFAULT 'idle',
            last_error TEXT
        )""",
            """CREATE TABLE IF NOT EXISTS airports (
            iata_code TEXT PRIMARY KEY,
            icao_code TEXT,
            name TEXT NOT NULL,
            city_name TEXT,
            country_code TEXT,
            latitude REAL,
            longitude REAL
        )""",
            """CREATE TABLE IF NOT EXISTS trips (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            booking_refs TEXT DEFAULT '[]',
            start_date TEXT,
            end_date TEXT,
            origin_airport TEXT,
            destination_airport TEXT,
            is_auto_generated INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
            """CREATE TABLE IF NOT EXISTS flights (
            id TEXT PRIMARY KEY,
            trip_id TEXT REFERENCES trips(id) ON DELETE SET NULL,
            airline_name TEXT,
            airline_code TEXT,
            flight_number TEXT NOT NULL,
            booking_reference TEXT,
            departure_airport TEXT NOT NULL,
            departure_datetime TEXT NOT NULL,
            departure_terminal TEXT,
            departure_gate TEXT,
            arrival_airport TEXT NOT NULL,
            arrival_datetime TEXT NOT NULL,
            arrival_terminal TEXT,
            arrival_gate TEXT,
            passenger_name TEXT,
            seat TEXT,
            cabin_class TEXT,
            duration_minutes INTEGER,
            status TEXT DEFAULT 'upcoming',
            departure_timezone TEXT,
            arrival_timezone TEXT,
            email_message_id TEXT UNIQUE,
            email_subject TEXT,
            email_date TEXT,
            aircraft_type TEXT,
            aircraft_icao TEXT,
            aircraft_fetched_at TEXT,
            is_manually_added INTEGER DEFAULT 0,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
            """CREATE TABLE IF NOT EXISTS aircraft_types (
            iata_code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            manufacturer TEXT
        )""",
            "CREATE INDEX IF NOT EXISTS idx_flights_trip_id ON flights(trip_id)",
            "CREATE INDEX IF NOT EXISTS idx_flights_departure ON flights(departure_datetime)",
            "CREATE INDEX IF NOT EXISTS idx_flights_booking_ref ON flights(booking_reference)",
            "CREATE INDEX IF NOT EXISTS idx_trips_start_date ON trips(start_date)",
        ],
    ),
    (
        2,
        "Add email_body and aircraft_registration columns to flights",
        [
            "ALTER TABLE flights ADD COLUMN email_body TEXT",
            "ALTER TABLE flights ADD COLUMN aircraft_registration TEXT",
        ],
    ),
    (
        3,
        "Add users table",
        [
            """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            smtp_recipient_address TEXT,
            gmail_address TEXT,
            gmail_app_password TEXT,
            imap_host TEXT,
            imap_port INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )""",
        ],
    ),
    (
        4,
        "Add user_id column to flights and trips",
        [
            "ALTER TABLE flights ADD COLUMN user_id INTEGER REFERENCES users(id)",
            "ALTER TABLE trips ADD COLUMN user_id INTEGER REFERENCES users(id)",
            "CREATE INDEX IF NOT EXISTS idx_flights_user_id ON flights(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_trips_user_id ON trips(user_id)",
        ],
    ),
    (
        5,
        "Migrate email_sync_state to support per-user rows",
        [
            """CREATE TABLE IF NOT EXISTS email_sync_state_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            last_synced_at TEXT,
            last_rules_version TEXT,
            status TEXT DEFAULT 'idle',
            last_error TEXT
        )""",
            """INSERT OR IGNORE INTO email_sync_state_new
               (id, user_id, last_synced_at, last_rules_version, status, last_error)
           SELECT id, NULL, last_synced_at, last_rules_version, status, last_error
           FROM email_sync_state""",
            "DROP TABLE IF EXISTS email_sync_state",
            "ALTER TABLE email_sync_state_new RENAME TO email_sync_state",
            "CREATE INDEX IF NOT EXISTS idx_email_sync_state_user_id ON email_sync_state(user_id)",
        ],
    ),
    (
        6,
        "Add TOTP 2FA columns to users",
        [
            "ALTER TABLE users ADD COLUMN totp_secret TEXT",
            "ALTER TABLE users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0",
        ],
    ),
    (
        7,
        "Add per-user sync_interval_minutes to users",
        [
            "ALTER TABLE users ADD COLUMN sync_interval_minutes INTEGER NOT NULL DEFAULT 10",
        ],
    ),
    (
        8,
        "Move smtp_allowed_senders to per-user in users table",
        [
            "ALTER TABLE users ADD COLUMN smtp_allowed_senders TEXT",
        ],
    ),
    (
        9,
        "Add global_settings table for admin-configured values",
        [
            """CREATE TABLE IF NOT EXISTS global_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        )""",
        ],
    ),
    (
        10,
        "Add sessions table for server-side session revocation",
        [
            """CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked INTEGER NOT NULL DEFAULT 0
        )""",
            "CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)",
        ],
    ),
    (
        11,
        "Add auth_attempts table for TOTP lockout tracking",
        [
            """CREATE TABLE IF NOT EXISTS auth_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            attempt_type TEXT NOT NULL DEFAULT 'totp',
            success INTEGER NOT NULL DEFAULT 0,
            attempted_at TEXT NOT NULL DEFAULT (datetime('now'))
        )""",
            "CREATE INDEX IF NOT EXISTS idx_auth_attempts_lookup ON auth_attempts(user_id, attempt_type, attempted_at)",
        ],
    ),
    (
        12,
        "Add aircraft fetch backoff columns",
        [
            "ALTER TABLE flights ADD COLUMN aircraft_fetch_attempts INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE flights ADD COLUMN aircraft_next_retry_at TEXT",
        ],
    ),
    (
        13,
        "Add image_fetched_at to trips for per-trip destination image caching",
        [
            "ALTER TABLE trips ADD COLUMN image_fetched_at TEXT",
        ],
    ),
    (
        14,
        "Add Immich integration columns",
        [
            "ALTER TABLE users ADD COLUMN immich_url TEXT",
            "ALTER TABLE users ADD COLUMN immich_api_key TEXT",
            "ALTER TABLE trips ADD COLUMN immich_album_id TEXT",
        ],
    ),
    (
        15,
        "Add notification preference columns to users",
        [
            "ALTER TABLE users ADD COLUMN notif_flight_reminder INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE users ADD COLUMN notif_checkin_reminder INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE users ADD COLUMN notif_trip_reminder INTEGER NOT NULL DEFAULT 1",
        ],
    ),
    (
        16,
        "Add push_subscriptions table",
        [
            """CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            endpoint TEXT NOT NULL,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            user_agent TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user_id, endpoint)
        )""",
            "CREATE INDEX IF NOT EXISTS idx_push_subs_user_id ON push_subscriptions(user_id)",
        ],
    ),
    (
        17,
        "Add notification_log table",
        [
            """CREATE TABLE IF NOT EXISTS notification_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            flight_id TEXT,
            notif_type TEXT NOT NULL,
            sent_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user_id, flight_id, notif_type)
        )""",
            "CREATE INDEX IF NOT EXISTS idx_notif_log_lookup ON notification_log(user_id, flight_id, notif_type)",
        ],
    ),
    (
        18,
        "Add live flight status columns for delay/cancellation tracking",
        [
            "ALTER TABLE flights ADD COLUMN live_status TEXT",
            "ALTER TABLE flights ADD COLUMN live_departure_delay INTEGER",
            "ALTER TABLE flights ADD COLUMN live_arrival_delay INTEGER",
            "ALTER TABLE flights ADD COLUMN live_departure_actual TEXT",
            "ALTER TABLE flights ADD COLUMN live_arrival_estimated TEXT",
            "ALTER TABLE flights ADD COLUMN live_status_fetched_at TEXT",
        ],
    ),
    (
        19,
        "Add delay_alert notification preference to users",
        [
            "ALTER TABLE users ADD COLUMN notif_delay_alert INTEGER NOT NULL DEFAULT 1",
        ],
    ),
    (
        20,
        "Add locale preference to users",
        [
            "ALTER TABLE users ADD COLUMN locale TEXT NOT NULL DEFAULT 'en'",
        ],
    ),
    (
        21,
        "Add aircraft_confirmed flag for re-fetch within 24h of departure",
        [
            "ALTER TABLE flights ADD COLUMN aircraft_confirmed INTEGER NOT NULL DEFAULT 0",
        ],
    ),
    (
        22,
        "Add boarding_passes table",
        [
            """CREATE TABLE IF NOT EXISTS boarding_passes (
            id TEXT PRIMARY KEY,
            flight_id TEXT NOT NULL REFERENCES flights(id) ON DELETE CASCADE,
            passenger_name TEXT,
            seat TEXT,
            image_path TEXT,
            source_email_id TEXT,
            source_page INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(source_email_id, source_page)
        )""",
            "CREATE INDEX IF NOT EXISTS idx_boarding_passes_flight_id ON boarding_passes(flight_id)",
        ],
    ),
    (
        23,
        "Add boarding_pass notification preference to users",
        [
            "ALTER TABLE users ADD COLUMN notif_boarding_pass INTEGER NOT NULL DEFAULT 1",
        ],
    ),
    (
        24,
        "Add failed_emails table for parse failures",
        [
            """CREATE TABLE IF NOT EXISTS failed_emails (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                sender TEXT NOT NULL,
                subject TEXT NOT NULL,
                received_at TEXT,
                reason TEXT NOT NULL,
                airline_hint TEXT NOT NULL DEFAULT '',
                eml_path TEXT,
                last_retried_at TEXT,
                parser_version TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""",
            "CREATE INDEX IF NOT EXISTS idx_failed_emails_user_id ON failed_emails(user_id)",
        ],
    ),
    (
        25,
        "Backfill notif_delay_alert column missed by v19 renumbering",
        [
            "ALTER TABLE users ADD COLUMN notif_delay_alert INTEGER NOT NULL DEFAULT 1",
        ],
    ),
]

def _get_alembic_config():
    from pathlib import Path

    from alembic.config import Config

    ini_path = Path(__file__).parent.parent / "alembic.ini"
    cfg = Config(str(ini_path))
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
            "Legacy DB detected (PRAGMA user_version=%d) — stamping Alembic at head",
            old_version,
        )
        command.stamp(cfg, "head")
        with db_write() as c:
            c.execute("PRAGMA user_version = 0")
    else:
        command.upgrade(cfg, "head")


def _encrypt_existing_credentials() -> None:
    """One-time migration: encrypt any plaintext credentials in the users table."""
    if get_global_setting("credentials_encrypted") == "true":
        return

    from .crypto import encrypt, is_encrypted

    with db_conn() as conn:
        users = conn.execute(
            "SELECT id, gmail_app_password, immich_api_key FROM users"
        ).fetchall()

    for user in users:
        updates: dict = {}
        pwd = user["gmail_app_password"]
        if pwd and not is_encrypted(pwd):
            updates["gmail_app_password"] = encrypt(pwd)
        key = user["immich_api_key"]
        if key and not is_encrypted(key):
            updates["immich_api_key"] = encrypt(key)
        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            with db_write() as conn:
                conn.execute(
                    f"UPDATE users SET {set_clause} WHERE id = ?",  # noqa: S608
                    list(updates.values()) + [user["id"]],
                )

    set_global_setting("credentials_encrypted", "true")
    logger.info("Credential encryption migration complete")


def init_database():
    """Run pending Alembic migrations then seed static data."""
    logger.info("Initializing database at %s", get_db_path())
    _run_alembic_migrations()
    _encrypt_existing_credentials()
    _normalize_aircraft_types()
    load_aircraft_types_if_empty()
    logger.info("Database ready")


def _normalize_aircraft_types():
    """One-time data fix: resolve raw IATA codes in aircraft_type to human-readable names."""
    with db_write() as conn:
        rows = conn.execute(
            "SELECT id, aircraft_type FROM flights "
            "WHERE aircraft_type IS NOT NULL AND aircraft_type != '' "
            "AND aircraft_type NOT LIKE '% %'"
        ).fetchall()
        for row in rows:
            resolved = conn.execute(
                "SELECT name FROM aircraft_types WHERE iata_code = ?",
                (row["aircraft_type"].upper(),),
            ).fetchone()
            if resolved:
                conn.execute(
                    "UPDATE flights SET aircraft_type = ? WHERE id = ?",
                    (resolved["name"], row["id"]),
                )


_AIRCRAFT_TYPES: list[tuple[str, str, str]] = [
    # (iata_code, name, manufacturer)
    # Airbus narrow-body
    ("A318", "Airbus A318", "Airbus"),
    ("A319", "Airbus A319", "Airbus"),
    ("A320", "Airbus A320", "Airbus"),
    ("A321", "Airbus A321", "Airbus"),
    ("A19N", "Airbus A319neo", "Airbus"),
    ("A20N", "Airbus A320neo", "Airbus"),
    ("A21N", "Airbus A321neo", "Airbus"),
    ("A21X", "Airbus A321XLR", "Airbus"),
    # Airbus wide-body
    ("A225", "Airbus A220-100", "Airbus"),
    ("A223", "Airbus A220-300", "Airbus"),
    ("BCS1", "Airbus A220-100", "Airbus"),
    ("BCS3", "Airbus A220-300", "Airbus"),
    ("A332", "Airbus A330-200", "Airbus"),
    ("A333", "Airbus A330-300", "Airbus"),
    ("A338", "Airbus A330-800neo", "Airbus"),
    ("A339", "Airbus A330-900neo", "Airbus"),
    ("A342", "Airbus A340-200", "Airbus"),
    ("A343", "Airbus A340-300", "Airbus"),
    ("A345", "Airbus A340-500", "Airbus"),
    ("A346", "Airbus A340-600", "Airbus"),
    ("A359", "Airbus A350-900", "Airbus"),
    ("A35K", "Airbus A350-1000", "Airbus"),
    ("A380", "Airbus A380-800", "Airbus"),
    ("A388", "Airbus A380-800", "Airbus"),
    # Boeing narrow-body
    ("B712", "Boeing 717-200", "Boeing"),
    ("B721", "Boeing 727-100", "Boeing"),
    ("B722", "Boeing 727-200", "Boeing"),
    ("B732", "Boeing 737-200", "Boeing"),
    ("B733", "Boeing 737-300", "Boeing"),
    ("B734", "Boeing 737-400", "Boeing"),
    ("B735", "Boeing 737-500", "Boeing"),
    ("B736", "Boeing 737-600", "Boeing"),
    ("B737", "Boeing 737-700", "Boeing"),
    ("B738", "Boeing 737-800", "Boeing"),
    ("B739", "Boeing 737-900", "Boeing"),
    ("B37M", "Boeing 737 MAX 7", "Boeing"),
    ("B38M", "Boeing 737 MAX 8", "Boeing"),
    ("B39M", "Boeing 737 MAX 9", "Boeing"),
    ("B3XM", "Boeing 737 MAX 10", "Boeing"),
    # Boeing wide-body
    ("B741", "Boeing 747-100", "Boeing"),
    ("B742", "Boeing 747-200", "Boeing"),
    ("B743", "Boeing 747-300", "Boeing"),
    ("B744", "Boeing 747-400", "Boeing"),
    ("B748", "Boeing 747-8", "Boeing"),
    ("B74S", "Boeing 747SP", "Boeing"),
    ("B752", "Boeing 757-200", "Boeing"),
    ("B753", "Boeing 757-300", "Boeing"),
    ("B762", "Boeing 767-200", "Boeing"),
    ("B763", "Boeing 767-300", "Boeing"),
    ("B764", "Boeing 767-400", "Boeing"),
    ("B772", "Boeing 777-200", "Boeing"),
    ("B77L", "Boeing 777-200LR", "Boeing"),
    ("B773", "Boeing 777-300", "Boeing"),
    ("B77W", "Boeing 777-300ER", "Boeing"),
    ("B778", "Boeing 777X-8", "Boeing"),
    ("B779", "Boeing 777X-9", "Boeing"),
    ("B788", "Boeing 787-8 Dreamliner", "Boeing"),
    ("B789", "Boeing 787-9 Dreamliner", "Boeing"),
    ("B78X", "Boeing 787-10 Dreamliner", "Boeing"),
    # Embraer
    ("E135", "Embraer ERJ-135", "Embraer"),
    ("E140", "Embraer ERJ-140", "Embraer"),
    ("E145", "Embraer ERJ-145", "Embraer"),
    ("E170", "Embraer E170", "Embraer"),
    ("E175", "Embraer E175", "Embraer"),
    ("E190", "Embraer E190", "Embraer"),
    ("E195", "Embraer E195", "Embraer"),
    ("E75L", "Embraer E175-E2", "Embraer"),
    ("E75S", "Embraer E175-E2", "Embraer"),
    ("E290", "Embraer E190-E2", "Embraer"),
    ("E295", "Embraer E195-E2", "Embraer"),
    # ATR
    ("AT43", "ATR 42-300", "ATR"),
    ("AT45", "ATR 42-500", "ATR"),
    ("AT46", "ATR 42-600", "ATR"),
    ("AT72", "ATR 72-200", "ATR"),
    ("AT73", "ATR 72-300", "ATR"),
    ("AT75", "ATR 72-500", "ATR"),
    ("AT76", "ATR 72-600", "ATR"),
    # Bombardier / CRJ
    ("CRJ1", "Bombardier CRJ-100", "Bombardier"),
    ("CRJ2", "Bombardier CRJ-200", "Bombardier"),
    ("CRJ7", "Bombardier CRJ-700", "Bombardier"),
    ("CRJ9", "Bombardier CRJ-900", "Bombardier"),
    ("CRJX", "Bombardier CRJ-1000", "Bombardier"),
    ("DH8A", "Bombardier Dash 8-100", "Bombardier"),
    ("DH8B", "Bombardier Dash 8-200", "Bombardier"),
    ("DH8C", "Bombardier Dash 8-300", "Bombardier"),
    ("DH8D", "Bombardier Dash 8-400", "Bombardier"),
    # McDonnell Douglas / MD
    ("MD11", "McDonnell Douglas MD-11", "McDonnell Douglas"),
    ("MD81", "McDonnell Douglas MD-81", "McDonnell Douglas"),
    ("MD82", "McDonnell Douglas MD-82", "McDonnell Douglas"),
    ("MD83", "McDonnell Douglas MD-83", "McDonnell Douglas"),
    ("MD87", "McDonnell Douglas MD-87", "McDonnell Douglas"),
    ("MD88", "McDonnell Douglas MD-88", "McDonnell Douglas"),
    ("MD90", "McDonnell Douglas MD-90", "McDonnell Douglas"),
    ("DC10", "Douglas DC-10", "McDonnell Douglas"),
    # Fokker
    ("F100", "Fokker 100", "Fokker"),
    ("F70", "Fokker 70", "Fokker"),
    ("F50", "Fokker 50", "Fokker"),
    ("F27", "Fokker 27 Friendship", "Fokker"),
    # Sukhoi / Irkut
    ("SU95", "Sukhoi Superjet 100", "Sukhoi"),
    ("SU9S", "Sukhoi Superjet 100", "Sukhoi"),
    # Comac
    ("C919", "Comac C919", "Comac"),
    ("ARJ1", "Comac ARJ21", "Comac"),
    # Saab
    ("SB20", "Saab 2000", "Saab"),
    ("SF34", "Saab 340", "Saab"),
    # Cessna / Beechcraft
    ("C208", "Cessna 208 Caravan", "Cessna"),
    ("B190", "Beechcraft 1900", "Beechcraft"),
    # De Havilland Canada
    ("DHC6", "De Havilland Canada Twin Otter", "De Havilland Canada"),
    ("DH6", "De Havilland Canada Twin Otter", "De Havilland Canada"),
]


def load_aircraft_types_if_empty():
    """Pre-populate the aircraft_types table on first run."""
    with db_conn() as conn:
        row = conn.execute("SELECT COUNT(*) FROM aircraft_types").fetchone()
        if row[0] > 0:
            return

    logger.info("Populating aircraft_types table with %d entries", len(_AIRCRAFT_TYPES))
    with db_write() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO aircraft_types (iata_code, name, manufacturer) VALUES (?, ?, ?)",
            _AIRCRAFT_TYPES,
        )


def load_airports_if_empty():
    """
    Load airports from data/airports.csv if the airports table is empty.
    The CSV should be downloaded from https://ourairports.com/data/airports.csv
    and placed in the data/ directory.
    """
    import csv
    from pathlib import Path

    with db_conn() as conn:
        row = conn.execute("SELECT COUNT(*) FROM airports").fetchone()
        if row[0] > 0:
            logger.debug("Airports table already populated (%d rows)", row[0])
            return

    csv_path = Path(get_db_path()).parent / "airports.csv"
    if not csv_path.exists():
        logger.info("airports.csv not found — downloading from ourairports.com ...")
        try:
            import urllib.request

            url = "https://davidmegginson.github.io/ourairports-data/airports.csv"
            urllib.request.urlretrieve(url, csv_path)
            logger.info("Downloaded airports.csv to %s", csv_path)
        except Exception as e:
            logger.warning("Could not download airports.csv: %s — airport lookups unavailable", e)
            return

    logger.info("Loading airports from %s ...", csv_path)
    rows = []
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for record in reader:
                iata = (record.get("iata_code") or "").strip().upper()
                if not iata or len(iata) != 3:
                    continue
                rows.append(
                    (
                        iata,
                        (record.get("icao_code") or "").strip().upper() or None,
                        (record.get("name") or "").strip(),
                        (record.get("municipality") or "").strip() or None,
                        (record.get("iso_country") or "").strip() or None,
                        _float_or_none(record.get("latitude_deg")),
                        _float_or_none(record.get("longitude_deg")),
                    )
                )
    except Exception as e:
        logger.error("Failed to read airports.csv: %s", e)
        return

    with db_write() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO airports "
            "(iata_code, icao_code, name, city_name, country_code, latitude, longitude) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    logger.info("Loaded %d airports", len(rows))


def _float_or_none(val):
    try:
        return float(val) if val else None
    except (ValueError, TypeError):
        return None
