"""Baseline schema — full schema at the point Alembic was adopted (v25 equivalent).

Fresh installs run this migration to build the DB from scratch.
Existing databases that used the old PRAGMA user_version system are stamped at
this revision by init_database() without running this SQL.

Revision ID: 0001
Revises: -
Create Date: 2026-03-22
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS airports (
            iata_code TEXT PRIMARY KEY,
            icao_code TEXT,
            name TEXT NOT NULL,
            city_name TEXT,
            country_code TEXT,
            latitude REAL,
            longitude REAL
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS aircraft_types (
            iata_code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            manufacturer TEXT
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS global_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            smtp_recipient_address TEXT,
            gmail_address TEXT,
            gmail_app_password TEXT,
            imap_host TEXT,
            imap_port INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            totp_secret TEXT,
            totp_enabled INTEGER NOT NULL DEFAULT 0,
            sync_interval_minutes INTEGER NOT NULL DEFAULT 10,
            smtp_allowed_senders TEXT,
            immich_url TEXT,
            immich_api_key TEXT,
            notif_flight_reminder INTEGER NOT NULL DEFAULT 1,
            notif_checkin_reminder INTEGER NOT NULL DEFAULT 1,
            notif_trip_reminder INTEGER NOT NULL DEFAULT 1,
            notif_delay_alert INTEGER NOT NULL DEFAULT 1,
            locale TEXT NOT NULL DEFAULT 'en',
            notif_boarding_pass INTEGER NOT NULL DEFAULT 1
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked INTEGER NOT NULL DEFAULT 0
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS auth_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            attempt_type TEXT NOT NULL DEFAULT 'totp',
            success INTEGER NOT NULL DEFAULT 0,
            attempted_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_auth_attempts_lookup "
        "ON auth_attempts(user_id, attempt_type, attempted_at)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            endpoint TEXT NOT NULL,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            user_agent TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user_id, endpoint)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_push_subs_user_id ON push_subscriptions(user_id)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS trips (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            booking_refs TEXT DEFAULT '[]',
            start_date TEXT,
            end_date TEXT,
            origin_airport TEXT,
            destination_airport TEXT,
            is_auto_generated INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            user_id INTEGER REFERENCES users(id),
            image_fetched_at TEXT,
            immich_album_id TEXT
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_trips_start_date ON trips(start_date)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_trips_user_id ON trips(user_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS flights (
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
            updated_at TEXT NOT NULL,
            email_body TEXT,
            aircraft_registration TEXT,
            user_id INTEGER REFERENCES users(id),
            aircraft_fetch_attempts INTEGER NOT NULL DEFAULT 0,
            aircraft_next_retry_at TEXT,
            live_status TEXT,
            live_departure_delay INTEGER,
            live_arrival_delay INTEGER,
            live_departure_actual TEXT,
            live_arrival_estimated TEXT,
            live_status_fetched_at TEXT,
            aircraft_confirmed INTEGER NOT NULL DEFAULT 0
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_flights_trip_id ON flights(trip_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_flights_departure ON flights(departure_datetime)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_flights_booking_ref ON flights(booking_reference)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_flights_user_id ON flights(user_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS notification_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            flight_id TEXT,
            notif_type TEXT NOT NULL,
            sent_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user_id, flight_id, notif_type)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_notif_log_lookup "
        "ON notification_log(user_id, flight_id, notif_type)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS email_sync_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            last_synced_at TEXT,
            last_rules_version TEXT,
            status TEXT DEFAULT 'idle',
            last_error TEXT
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_email_sync_state_user_id "
        "ON email_sync_state(user_id)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS boarding_passes (
            id TEXT PRIMARY KEY,
            flight_id TEXT NOT NULL REFERENCES flights(id) ON DELETE CASCADE,
            passenger_name TEXT,
            seat TEXT,
            image_path TEXT,
            source_email_id TEXT,
            source_page INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(source_email_id, source_page)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_boarding_passes_flight_id "
        "ON boarding_passes(flight_id)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS failed_emails (
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
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_failed_emails_user_id ON failed_emails(user_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS failed_emails")
    op.execute("DROP TABLE IF EXISTS boarding_passes")
    op.execute("DROP TABLE IF EXISTS email_sync_state")
    op.execute("DROP TABLE IF EXISTS notification_log")
    op.execute("DROP TABLE IF EXISTS flights")
    op.execute("DROP TABLE IF EXISTS trips")
    op.execute("DROP TABLE IF EXISTS push_subscriptions")
    op.execute("DROP TABLE IF EXISTS auth_attempts")
    op.execute("DROP TABLE IF EXISTS sessions")
    op.execute("DROP TABLE IF EXISTS users")
    op.execute("DROP TABLE IF EXISTS global_settings")
    op.execute("DROP TABLE IF EXISTS aircraft_types")
    op.execute("DROP TABLE IF EXISTS airports")
