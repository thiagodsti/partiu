"""Repository for the `trips` table and the read-heavy joins needed to enrich a
trip with flight counts, owner usernames, expense totals, Immich album links, and
the pre-normalised search index."""

import sqlite3

from ..database import db_conn, db_write
from .domain import Trip
from .mappers import row_to_trip


class TripRepository:
    # -- Reads: single/bulk trips -------------------------------------------

    def list_owned(self, user_id: int) -> list[Trip]:
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trips WHERE user_id = ? ORDER BY start_date ASC", (user_id,)
            ).fetchall()
        return [row_to_trip(r) for r in rows]

    def list_shared_accepted(self, user_id: int) -> list[Trip]:
        with db_conn() as conn:
            rows = conn.execute(
                """SELECT t.* FROM trips t
                   JOIN trip_shares ts ON ts.trip_id = t.id
                   WHERE ts.user_id = ? AND ts.status = 'accepted'
                   ORDER BY t.start_date ASC""",
                (user_id,),
            ).fetchall()
        return [row_to_trip(r) for r in rows]

    def get_by_id(self, trip_id: str) -> Trip | None:
        with db_conn() as conn:
            row = conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
        return row_to_trip(row) if row else None

    def get_flights_for_trip(self, trip_id: str) -> list[dict]:
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM flights WHERE trip_id = ? ORDER BY departure_datetime",
                (trip_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_owner_username(self, user_id: int | None) -> str | None:
        if user_id is None:
            return None
        with db_conn() as conn:
            row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        return row["username"] if row else None

    # -- Bulk "attach extras" queries for the list endpoint -------------------

    def get_flight_counts(self, trip_ids: list[str]) -> dict[str, int]:
        if not trip_ids:
            return {}
        placeholders = ",".join("?" * len(trip_ids))
        with db_conn() as conn:
            rows = conn.execute(
                f"SELECT trip_id, COUNT(*) AS cnt FROM flights WHERE trip_id IN ({placeholders}) GROUP BY trip_id",
                trip_ids,
            ).fetchall()
        return {r["trip_id"]: r["cnt"] for r in rows}

    def get_segment_counts(self, trip_ids: list[str]) -> dict[str, int]:
        """Ground legs per trip, for the trips-list card.

        A sibling of get_flight_counts rather than a UNION with it: the card
        names each kind separately ("2 trains", not "2 legs"), so the counts
        have to stay apart.
        """
        return self._count_by_trip("trip_segments", trip_ids)

    def get_stay_counts(self, trip_ids: list[str]) -> dict[str, int]:
        """Stays per trip, for the trips-list card."""
        return self._count_by_trip("trip_stays", trip_ids)

    @staticmethod
    def _count_by_trip(table: str, trip_ids: list[str]) -> dict[str, int]:
        if not trip_ids:
            return {}
        placeholders = ",".join("?" * len(trip_ids))
        with db_conn() as conn:
            rows = conn.execute(
                f"SELECT trip_id, COUNT(*) AS cnt FROM {table} "
                f"WHERE trip_id IN ({placeholders}) GROUP BY trip_id",
                trip_ids,
            ).fetchall()
        return {r["trip_id"]: r["cnt"] for r in rows}

    def get_segment_types(self, trip_ids: list[str]) -> dict[str, list[str]]:
        """The distinct transport types on each trip, so a card can say "trains"
        rather than the generic "legs" when a trip only uses one kind."""
        if not trip_ids:
            return {}
        placeholders = ",".join("?" * len(trip_ids))
        with db_conn() as conn:
            rows = conn.execute(
                f"SELECT DISTINCT trip_id, type FROM trip_segments "
                f"WHERE trip_id IN ({placeholders})",
                trip_ids,
            ).fetchall()
        out: dict[str, list[str]] = {}
        for r in rows:
            out.setdefault(r["trip_id"], []).append(r["type"])
        return {k: sorted(v) for k, v in out.items()}

    def get_usernames(self, user_ids: list[int]) -> dict[int, str]:
        if not user_ids:
            return {}
        placeholders = ",".join("?" * len(user_ids))
        with db_conn() as conn:
            rows = conn.execute(
                f"SELECT id, username FROM users WHERE id IN ({placeholders})", user_ids
            ).fetchall()
        return {r["id"]: r["username"] for r in rows}

    def get_expenses_totals(self, trip_ids: list[str]) -> dict[str, dict[str, float]]:
        if not trip_ids:
            return {}
        placeholders = ",".join("?" * len(trip_ids))
        with db_conn() as conn:
            rows = conn.execute(
                f"SELECT trip_id, currency, SUM(amount) AS total"
                f" FROM trip_expenses WHERE trip_id IN ({placeholders})"
                f" GROUP BY trip_id, currency",
                trip_ids,
            ).fetchall()
        totals: dict[str, dict[str, float]] = {}
        for r in rows:
            totals.setdefault(r["trip_id"], {})[r["currency"]] = r["total"]
        return totals

    def get_expenses_total(self, trip_id: str) -> dict[str, float]:
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT currency, SUM(amount) AS total FROM trip_expenses"
                " WHERE trip_id = ? GROUP BY currency",
                (trip_id,),
            ).fetchall()
        return {r["currency"]: r["total"] for r in rows}

    def get_immich_album_ids(self, trip_ids: list[str], user_id: int) -> dict[str, str]:
        if not trip_ids:
            return {}
        placeholders = ",".join("?" * len(trip_ids))
        with db_conn() as conn:
            rows = conn.execute(
                f"SELECT trip_id, album_id FROM trip_immich_albums"
                f" WHERE trip_id IN ({placeholders}) AND user_id = ?",
                [*trip_ids, user_id],
            ).fetchall()
        return {r["trip_id"]: r["album_id"] for r in rows}

    def get_immich_album_id(self, trip_id: str, user_id: int) -> str | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT album_id FROM trip_immich_albums WHERE trip_id = ? AND user_id = ?",
                (trip_id, user_id),
            ).fetchone()
        return row["album_id"] if row else None

    def get_search_index_rows(self, trip_ids: list[str]) -> dict[str, sqlite3.Row]:
        """One joined/aggregated row per trip with concatenated flight fields,
        used to build the pre-normalised full-text search index."""
        if not trip_ids:
            return {}
        placeholders = ",".join("?" * len(trip_ids))
        with db_conn() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    f.trip_id,
                    GROUP_CONCAT(COALESCE(f.departure_airport, ''), ' ') AS dep_iatas,
                    GROUP_CONCAT(COALESCE(f.arrival_airport,   ''), ' ') AS arr_iatas,
                    GROUP_CONCAT(COALESCE(dep.city_name,       ''), ' ') AS dep_cities,
                    GROUP_CONCAT(COALESCE(arr.city_name,       ''), ' ') AS arr_cities,
                    GROUP_CONCAT(COALESCE(dep.country_code,    ''), ' ') AS dep_countries,
                    GROUP_CONCAT(COALESCE(arr.country_code,    ''), ' ') AS arr_countries,
                    GROUP_CONCAT(COALESCE(f.airline_name,      ''), ' ') AS airlines,
                    GROUP_CONCAT(COALESCE(f.flight_number,     ''), ' ') AS flight_nums
                FROM flights f
                LEFT JOIN airports dep ON dep.iata_code = f.departure_airport
                LEFT JOIN airports arr ON arr.iata_code = f.arrival_airport
                WHERE f.trip_id IN ({placeholders})
                GROUP BY f.trip_id
                """,
                trip_ids,
            ).fetchall()
        return {r["trip_id"]: r for r in rows}

    # -- Writes: trip CRUD ---------------------------------------------------

    def create(
        self,
        trip_id: str,
        name: str,
        booking_refs_json: str,
        start_date: str,
        end_date: str,
        origin_airport: str,
        destination_airport: str,
        user_id: int,
        now: str,
        is_auto_generated: bool = False,
    ) -> None:
        with db_write() as conn:
            conn.execute(
                """INSERT INTO trips (id, name, booking_refs, start_date, end_date,
                   origin_airport, destination_airport, is_auto_generated, user_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trip_id,
                    name,
                    booking_refs_json,
                    start_date,
                    end_date,
                    origin_airport,
                    destination_airport,
                    1 if is_auto_generated else 0,
                    user_id,
                    now,
                    now,
                ),
            )

    def get_owned(self, trip_id: str, user_id: int) -> Trip | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT * FROM trips WHERE id = ? AND user_id = ?", (trip_id, user_id)
            ).fetchone()
        return row_to_trip(row) if row else None

    def update(self, trip_id: str, user_id: int, updates: dict) -> None:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        with db_write() as conn:
            conn.execute(
                f"UPDATE trips SET {set_clause} WHERE id = ? AND user_id = ?",
                (*updates.values(), trip_id, user_id),
            )

    def delete_owned(self, trip_id: str, user_id: int) -> None:
        """Delete a trip along with its flights (boarding_passes/trip_documents
        cascade via their own foreign keys)."""
        with db_write() as conn:
            conn.execute(
                "DELETE FROM flights WHERE trip_id = ? AND user_id = ?", (trip_id, user_id)
            )
            conn.execute("DELETE FROM trips WHERE id = ? AND user_id = ?", (trip_id, user_id))

    # -- Merge -----------------------------------------------------------------

    def merge_trips(self, source_trip_id: str, target_trip_id: str, user_id: int, now: str) -> None:
        """Move all flights from source into target, delete source, then recompute
        target's span — all in one transaction, matching the original route."""
        with db_write() as conn:
            conn.execute(
                "UPDATE flights SET trip_id = ?, updated_at = ? WHERE trip_id = ?",
                (target_trip_id, now, source_trip_id),
            )
            conn.execute(
                "DELETE FROM trips WHERE id = ? AND user_id = ?", (source_trip_id, user_id)
            )
            self._recompute_span(conn, target_trip_id, now)

    def recompute_span(self, trip_id: str, now: str) -> None:
        """Standalone version of the span recompute, for callers (e.g. the flights
        feature, after creating/updating a flight) that aren't already inside a
        trips-repository write transaction."""
        with db_write() as conn:
            self._recompute_span(conn, trip_id, now)

    @staticmethod
    def _recompute_span(conn, trip_id: str, now: str) -> None:
        """Recalculate start/end dates and airports from everything now in the
        trip. start_date = earliest departure; end_date = latest arrival.

        Dates span **flights, ground segments and stays** together: a trip whose
        middle days are a train leg would otherwise end on its last flight, and
        the day planner — which renders one card per day in the trip's range —
        would have no card for those days to appear in. Stays count for the same
        reason and one more: accommodation is frequently booked before any
        transport is, so a stays-only trip must still have a span.

        Stays contribute their pre-computed local `check_in_date` /
        `check_out_date` columns rather than `DATE(check_in_datetime)`. The
        stored instants are UTC and SQLite cannot convert zones, so a 15:00
        check-in at a property in UTC-10 would otherwise widen the span by a day
        in the wrong direction.

        Origin/destination stay flight-only. They are IATA codes used for trip
        cards and the destination photo lookup; a train station has no code to
        put there.

        MIN/MAX are the aggregate forms, not the two-argument scalar ones: the
        scalars return NULL when either side is NULL, which would blank the span
        of a trip that has flights but no segments (or the reverse).
        """
        conn.execute(
            """UPDATE trips SET
                start_date = (
                    SELECT MIN(d) FROM (
                        SELECT DATE(departure_datetime) AS d FROM flights WHERE trip_id = ?
                        UNION ALL
                        SELECT DATE(departure_datetime) FROM trip_segments WHERE trip_id = ?
                        UNION ALL
                        SELECT check_in_date FROM trip_stays WHERE trip_id = ?
                    )
                ),
                end_date = (
                    SELECT MAX(d) FROM (
                        SELECT DATE(arrival_datetime) AS d FROM flights WHERE trip_id = ?
                        UNION ALL
                        SELECT DATE(arrival_datetime) FROM trip_segments WHERE trip_id = ?
                        UNION ALL
                        SELECT check_out_date FROM trip_stays WHERE trip_id = ?
                    )
                ),
                origin_airport = (
                    SELECT departure_airport FROM flights WHERE trip_id = ?
                    ORDER BY datetime(departure_datetime) ASC LIMIT 1
                ),
                destination_airport = (
                    SELECT arrival_airport FROM flights WHERE trip_id = ?
                    ORDER BY datetime(departure_datetime) DESC LIMIT 1
                ),
                updated_at = ?
            WHERE id = ?""",
            (trip_id,) * 8 + (now, trip_id),
        )

    # -- Flight assignment -----------------------------------------------------

    def trip_owned_exists(self, trip_id: str, user_id: int) -> bool:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT id FROM trips WHERE id = ? AND user_id = ?", (trip_id, user_id)
            ).fetchone()
        return row is not None

    def flight_owned_exists(self, flight_id: str, user_id: int) -> bool:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT id FROM flights WHERE id = ? AND user_id = ?", (flight_id, user_id)
            ).fetchone()
        return row is not None

    def assign_flight(self, flight_id: str, trip_id: str, user_id: int, now: str) -> None:
        with db_write() as conn:
            conn.execute(
                "UPDATE flights SET trip_id = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (trip_id, now, flight_id, user_id),
            )

    def unassign_flight(self, flight_id: str, trip_id: str, user_id: int, now: str) -> None:
        with db_write() as conn:
            conn.execute(
                "UPDATE flights SET trip_id = NULL, updated_at = ? WHERE id = ? AND trip_id = ? AND user_id = ?",
                (now, flight_id, trip_id, user_id),
            )

    # -- Destination city resolution (for the image feature) ------------------

    def get_destination_airport(self, trip_id: str) -> str | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT destination_airport FROM trips WHERE id = ?", (trip_id,)
            ).fetchone()
        return row["destination_airport"] if row else None

    def get_last_flight_arrival_airport(self, trip_id: str) -> str | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT arrival_airport FROM flights WHERE trip_id = ? "
                "ORDER BY departure_datetime DESC LIMIT 1",
                (trip_id,),
            ).fetchone()
        return row["arrival_airport"] if row else None

    def get_airport_city(self, iata: str) -> str | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT city_name FROM airports WHERE iata_code = ?", (iata.upper(),)
            ).fetchone()
        return row["city_name"] if row and row["city_name"] else None

    # -- Trip image --------------------------------------------------------

    def set_image_fetched_at(self, trip_id: str, now: str) -> None:
        with db_write() as conn:
            conn.execute("UPDATE trips SET image_fetched_at = ? WHERE id = ?", (now, trip_id))

    # -- Immich album --------------------------------------------------------

    def get_immich_credentials(self, user_id: int) -> sqlite3.Row | None:
        with db_conn() as conn:
            return conn.execute(
                "SELECT immich_url, immich_api_key FROM users WHERE id = ?", (user_id,)
            ).fetchone()

    def save_immich_album(self, trip_id: str, user_id: int, album_id: str) -> None:
        with db_write() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO trip_immich_albums (trip_id, user_id, album_id) VALUES (?, ?, ?)",
                (trip_id, user_id, album_id),
            )

    def delete_immich_album(self, trip_id: str, user_id: int) -> None:
        with db_write() as conn:
            conn.execute(
                "DELETE FROM trip_immich_albums WHERE trip_id = ? AND user_id = ?",
                (trip_id, user_id),
            )

    # -- Rating / note (owner + shared collaborators) ---------------------

    def set_rating(self, trip_id: str, rating: float | None, now: str) -> None:
        with db_write() as conn:
            conn.execute(
                "UPDATE trips SET rating = ?, updated_at = ? WHERE id = ?", (rating, now, trip_id)
            )

    def set_note(self, trip_id: str, note: str | None, now: str) -> None:
        with db_write() as conn:
            conn.execute(
                "UPDATE trips SET note = ?, updated_at = ? WHERE id = ?", (note, now, trip_id)
            )
