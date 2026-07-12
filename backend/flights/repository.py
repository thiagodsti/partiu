"""Repository for the `flights` table."""

import sqlite3

from ..database import db_conn, db_write
from .domain import Flight
from .mappers import row_to_flight


class FlightRepository:
    # -- Reads -----------------------------------------------------------------

    def list_for_export(self, user_id: int) -> list[sqlite3.Row]:
        """Completed flights joined with airport coords/city/country + trip name,
        for the CSV export."""
        with db_conn() as conn:
            return conn.execute(
                """
                SELECT
                    f.flight_number, f.airline_code, f.airline_name,
                    f.departure_airport, f.arrival_airport,
                    f.departure_datetime, f.arrival_datetime, f.duration_minutes,
                    f.seat, f.aircraft_type, f.booking_reference,
                    dep.city_name AS dep_city, dep.country_code AS dep_country,
                    dep.latitude AS dep_lat, dep.longitude AS dep_lon,
                    arr.city_name AS arr_city, arr.country_code AS arr_country,
                    arr.latitude AS arr_lat, arr.longitude AS arr_lon,
                    t.name AS trip_name
                FROM flights f
                LEFT JOIN airports dep ON dep.iata_code = f.departure_airport
                LEFT JOIN airports arr ON arr.iata_code = f.arrival_airport
                LEFT JOIN trips t ON t.id = f.trip_id
                WHERE f.user_id = ? AND f.status = 'completed'
                ORDER BY f.departure_datetime
                """,
                (user_id,),
            ).fetchall()

    def list_flights(
        self,
        user_id: int,
        trip_id: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Flight], int]:
        """Return flights, optionally filtered by trip or status, plus the total
        count (before limit/offset) for pagination."""
        with db_conn() as conn:
            if trip_id:
                query = "SELECT * FROM flights WHERE trip_id = ?"
                params: list = [trip_id]
                count_query = "SELECT COUNT(*) FROM flights WHERE trip_id = ?"
                count_params: list = [trip_id]
                if status:
                    query += " AND status = ?"
                    params.append(status)
                    count_query += " AND status = ?"
                    count_params.append(status)
            else:
                # User's own flights + flights from shared trips
                base_union = (
                    "SELECT f.* FROM flights f WHERE f.user_id = ? "
                    "UNION "
                    "SELECT f.* FROM flights f "
                    "JOIN trip_shares ts ON ts.trip_id = f.trip_id "
                    "WHERE ts.user_id = ? AND ts.status = 'accepted'"
                )
                params: list = [user_id, user_id]
                count_params: list = [user_id, user_id]
                if status:
                    query = f"SELECT * FROM ({base_union}) WHERE status = ?"
                    params.append(status)
                    count_query = f"SELECT COUNT(*) FROM ({base_union}) WHERE status = ?"
                    count_params.append(status)
                else:
                    query = base_union
                    count_query = f"SELECT COUNT(*) FROM ({base_union})"

            query += " ORDER BY departure_datetime DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(query, params).fetchall()
            total = conn.execute(count_query, count_params).fetchone()[0]

        return [row_to_flight(r) for r in rows], total

    def get_by_id(self, flight_id: str) -> Flight | None:
        with db_conn() as conn:
            row = conn.execute("SELECT * FROM flights WHERE id = ?", (flight_id,)).fetchone()
        return row_to_flight(row) if row else None

    def get_owned(self, flight_id: str, user_id: int) -> Flight | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT * FROM flights WHERE id = ? AND user_id = ?", (flight_id, user_id)
            ).fetchone()
        return row_to_flight(row) if row else None

    def get_email_fields(self, flight_id: str) -> sqlite3.Row | None:
        with db_conn() as conn:
            return conn.execute(
                "SELECT email_body, email_subject, email_date FROM flights WHERE id = ?",
                (flight_id,),
            ).fetchone()

    def get_aircraft_fields(self, flight_id: str) -> sqlite3.Row | None:
        with db_conn() as conn:
            return conn.execute(
                "SELECT flight_number, arrival_datetime, aircraft_type, aircraft_icao, "
                "aircraft_registration, aircraft_fetched_at FROM flights WHERE id = ?",
                (flight_id,),
            ).fetchone()

    def update_aircraft_recovery(
        self, flight_id: str, user_id: int, type_name: str, registration: str, now: str
    ) -> None:
        with db_write() as conn:
            conn.execute(
                "UPDATE flights SET aircraft_type = ?, aircraft_registration = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (type_name, registration, now, flight_id, user_id),
            )

    def recover_aircraft_name(
        self, flight_id: str, type_name: str, registration: str, now: str
    ) -> None:
        """Fill in type/registration recovered from a stored ICAO24. Unscoped by
        user_id — this is a system-level data-consistency sweep (background
        aircraft sync), not a per-request write."""
        with db_write() as conn:
            conn.execute(
                "UPDATE flights SET aircraft_type = ?, aircraft_registration = ?, updated_at = ? WHERE id = ?",
                (type_name, registration, now, flight_id),
            )

    def mark_aircraft_fetch_given_up(self, flight_id: str, now: str) -> None:
        """Mark a fetch attempt as done (without data) so the sync sweep stops
        retrying a flight that's too far past arrival."""
        with db_write() as conn:
            conn.execute(
                "UPDATE flights SET aircraft_fetched_at = ?, updated_at = ? WHERE id = ?",
                (now, now, flight_id),
            )

    def update_aircraft_fetch_result(
        self,
        flight_id: str,
        type_name: str,
        icao24: str,
        registration: str,
        confirmed: bool,
        now: str,
    ) -> None:
        """Record a successful aircraft fetch result and clear retry state."""
        with db_write() as conn:
            conn.execute(
                """UPDATE flights
                   SET aircraft_type = ?, aircraft_icao = ?, aircraft_registration = ?,
                       aircraft_fetched_at = ?, aircraft_confirmed = ?,
                       aircraft_fetch_attempts = 0, aircraft_next_retry_at = NULL,
                       updated_at = ?
                   WHERE id = ?""",
                (type_name, icao24, registration, now, int(confirmed), now, flight_id),
            )

    def schedule_aircraft_retry(self, flight_id: str, next_retry_at: str, now: str) -> None:
        """Bump the attempt counter and schedule the next backoff retry."""
        with db_write() as conn:
            conn.execute(
                """UPDATE flights
                   SET aircraft_fetch_attempts = aircraft_fetch_attempts + 1,
                       aircraft_next_retry_at = ?, updated_at = ?
                   WHERE id = ?""",
                (next_retry_at, now, flight_id),
            )

    def count_in_trip(self, trip_id: str) -> int:
        with db_conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM flights WHERE trip_id = ?", (trip_id,)
            ).fetchone()[0]

    def find_by_number_and_date(
        self, flight_number: str, departure_date: str, user_id: int
    ) -> Flight | None:
        """Find an existing non-manual flight by flight_number and departure date
        (used during email sync to detect updates vs. new flights)."""
        with db_conn() as conn:
            row = conn.execute(
                """SELECT * FROM flights
                   WHERE flight_number = ?
                   AND substr(departure_datetime, 1, 10) = ?
                   AND is_manually_added = 0
                   AND user_id = ?
                   LIMIT 1""",
                (flight_number, departure_date, user_id),
            ).fetchone()
        return row_to_flight(row) if row else None

    def find_latest_by_number(self, flight_number: str, user_id: int) -> Flight | None:
        """Find the most recent flight matching a flight number, regardless of date
        (used to guess a flight from free-text email content, e.g. boarding passes
        with no BCBP barcode to pin down the exact date)."""
        with db_conn() as conn:
            row = conn.execute(
                """SELECT * FROM flights
                   WHERE flight_number = ? AND user_id = ?
                   ORDER BY departure_datetime DESC LIMIT 1""",
                (flight_number, user_id),
            ).fetchone()
        return row_to_flight(row) if row else None

    def list_missing_aircraft_data(self, user_id: int, limit: int = 20) -> list[str]:
        """Return ids of the user's most recently created flights that haven't had
        an aircraft-type lookup attempted yet (used to trigger aircraft sync right
        after new flights are created, e.g. from inbound email processing)."""
        with db_conn() as conn:
            rows = conn.execute(
                """SELECT id FROM flights
                   WHERE aircraft_fetched_at IS NULL AND user_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
        return [r["id"] for r in rows]

    def get_aircraft_fetch_attempts(self, flight_id: str) -> int:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT aircraft_fetch_attempts FROM flights WHERE id = ?", (flight_id,)
            ).fetchone()
        return (row["aircraft_fetch_attempts"] if row else 0) or 0

    def list_missing_aircraft_names(self) -> list[sqlite3.Row]:
        """Flights with an ICAO24 stored but missing type name/registration —
        candidates for hexdb.io name recovery (background aircraft sync)."""
        with db_conn() as conn:
            return conn.execute(
                """SELECT id, aircraft_icao FROM flights
                   WHERE aircraft_icao != '' AND aircraft_icao IS NOT NULL
                     AND (aircraft_type IS NULL OR aircraft_type = ''
                          OR aircraft_registration IS NULL OR aircraft_registration = '')"""
            ).fetchall()

    def list_needing_aircraft_fetch(self, window_start: str, now: str) -> list[sqlite3.Row]:
        """Flights with no aircraft data yet, departing within the sync window and
        not currently in backoff (background aircraft sync's daily sweep)."""
        with db_conn() as conn:
            return conn.execute(
                """SELECT id, flight_number, arrival_datetime, departure_datetime
                   FROM flights
                   WHERE aircraft_fetched_at IS NULL
                     AND status != 'cancelled'
                     AND departure_datetime >= ? AND departure_datetime <= ?
                     AND (aircraft_next_retry_at IS NULL OR aircraft_next_retry_at <= ?)
                   ORDER BY departure_datetime""",
                (window_start, now, now),
            ).fetchall()

    def list_needing_aircraft_refresh(
        self, window_start: str, window_end: str
    ) -> list[sqlite3.Row]:
        """Flights fetched early (unconfirmed) that are now within 24h of departure —
        worth re-fetching since the API is more accurate close to the live window."""
        with db_conn() as conn:
            return conn.execute(
                """SELECT id, flight_number, arrival_datetime, departure_datetime
                   FROM flights
                   WHERE aircraft_fetched_at IS NOT NULL
                     AND aircraft_confirmed = 0
                     AND status != 'cancelled'
                     AND departure_datetime >= ? AND departure_datetime <= ?
                   ORDER BY departure_datetime""",
                (window_start, window_end),
            ).fetchall()

    def list_eligible_for_immediate_fetch(
        self, flight_ids: list[str], now: str
    ) -> list[sqlite3.Row]:
        """Of the given flight ids, those still eligible for an aircraft fetch attempt
        (used when a new flight is added, to try right away)."""
        if not flight_ids:
            return []
        placeholders = ",".join("?" * len(flight_ids))
        with db_conn() as conn:
            return conn.execute(
                f"""SELECT id, flight_number, arrival_datetime, departure_datetime
                    FROM flights
                    WHERE id IN ({placeholders})
                      AND aircraft_fetched_at IS NULL
                      AND status != 'cancelled'
                      AND (aircraft_next_retry_at IS NULL OR aircraft_next_retry_at <= ?)""",
                [*flight_ids, now],
            ).fetchall()

    # -- Writes ------------------------------------------------------------

    def create(self, flight_id: str, fields: dict, user_id: int, now: str) -> None:
        with db_write() as conn:
            conn.execute(
                """INSERT INTO flights (
                    id, trip_id, airline_name, airline_code, flight_number,
                    booking_reference, departure_airport, departure_datetime,
                    departure_terminal, departure_gate, arrival_airport, arrival_datetime,
                    arrival_terminal, arrival_gate, passenger_name, seat, cabin_class,
                    duration_minutes, status, departure_timezone, arrival_timezone,
                    is_manually_added, notes, user_id, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    1, ?, ?, ?, ?
                )""",
                (
                    flight_id,
                    fields["trip_id"],
                    fields["airline_name"],
                    fields["airline_code"],
                    fields["flight_number"],
                    fields["booking_reference"],
                    fields["departure_airport"],
                    fields["departure_datetime"],
                    fields["departure_terminal"],
                    fields["departure_gate"],
                    fields["arrival_airport"],
                    fields["arrival_datetime"],
                    fields["arrival_terminal"],
                    fields["arrival_gate"],
                    fields["passenger_name"],
                    fields["seat"],
                    fields["cabin_class"],
                    fields["duration_minutes"],
                    fields["status"],
                    fields["departure_timezone"],
                    fields["arrival_timezone"],
                    fields["notes"],
                    user_id,
                    now,
                    now,
                ),
            )

    def create_synced(self, flight_id: str, fields: dict, user_id: int, now: str) -> int:
        """INSERT OR IGNORE a flight extracted from email sync (dedup by
        ``fields["email_message_id"]``, which is namespaced per flight leg).
        Returns the row count — 0 means it was a duplicate."""
        with db_write() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO flights (
                    id, trip_id, airline_name, airline_code, flight_number,
                    booking_reference, departure_airport, departure_datetime,
                    departure_terminal, departure_gate, arrival_airport, arrival_datetime,
                    arrival_terminal, arrival_gate, passenger_name, seat, cabin_class,
                    duration_minutes, status, departure_timezone, arrival_timezone,
                    email_message_id, email_subject, email_date, email_body,
                    is_manually_added, notes, user_id, created_at, updated_at
                ) VALUES (
                    ?, NULL, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    0, NULL, ?, ?, ?
                )""",
                (
                    flight_id,
                    fields["airline_name"],
                    fields["airline_code"],
                    fields["flight_number"],
                    fields["booking_reference"],
                    fields["departure_airport"],
                    fields["departure_datetime"],
                    fields["departure_terminal"],
                    fields["departure_gate"],
                    fields["arrival_airport"],
                    fields["arrival_datetime"],
                    fields["arrival_terminal"],
                    fields["arrival_gate"],
                    fields["passenger_name"],
                    fields["seat"],
                    fields["cabin_class"],
                    fields["duration_minutes"],
                    fields["status"],
                    fields["departure_timezone"],
                    fields["arrival_timezone"],
                    fields["email_message_id"],
                    fields["email_subject"],
                    fields["email_date"],
                    fields["email_body"],
                    user_id,
                    now,
                    now,
                ),
            )
        return cursor.rowcount

    def update_synced(self, flight_id: str, fields: dict, now: str) -> None:
        """Update a synced flight with newer data re-parsed from a follow-up email."""
        with db_write() as conn:
            conn.execute(
                """UPDATE flights SET
                    departure_datetime = ?, arrival_datetime = ?,
                    departure_terminal = ?, arrival_terminal = ?,
                    departure_gate = ?, arrival_gate = ?,
                    seat = ?, cabin_class = ?,
                    booking_reference = ?, passenger_name = ?,
                    duration_minutes = ?, status = ?,
                    departure_timezone = ?, arrival_timezone = ?,
                    email_message_id = ?, email_subject = ?, email_date = ?, email_body = ?,
                    updated_at = ?
                   WHERE id = ?""",
                (
                    fields["departure_datetime"],
                    fields["arrival_datetime"],
                    fields["departure_terminal"],
                    fields["arrival_terminal"],
                    fields["departure_gate"],
                    fields["arrival_gate"],
                    fields["seat"],
                    fields["cabin_class"],
                    fields["booking_reference"],
                    fields["passenger_name"],
                    fields["duration_minutes"],
                    fields["status"],
                    fields["departure_timezone"],
                    fields["arrival_timezone"],
                    fields["email_message_id"],
                    fields["email_subject"],
                    fields["email_date"],
                    fields["email_body"],
                    now,
                    flight_id,
                ),
            )

    def update(self, flight_id: str, user_id: int, updates: dict) -> None:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        with db_write() as conn:
            conn.execute(
                f"UPDATE flights SET {set_clause} WHERE id = ? AND user_id = ?",
                (*updates.values(), flight_id, user_id),
            )

    def delete_owned(self, flight_id: str, user_id: int) -> None:
        with db_write() as conn:
            conn.execute("DELETE FROM flights WHERE id = ? AND user_id = ?", (flight_id, user_id))
