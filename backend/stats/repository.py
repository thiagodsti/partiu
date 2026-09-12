"""Repository for the raw flight data behind travel statistics.

No trip-sharing access control here — stats are always scoped to the requesting
user's own flights (``WHERE f.user_id = ?``), same as the original route.
"""

from ..database import db_conn
from .domain import FlightStatsRow
from .mappers import row_to_flight_stats_row


class StatsRepository:
    def list_completed_flights(self, user_id: int, year: int | None = None) -> list[FlightStatsRow]:
        year_clause = ""
        params: list = [user_id]
        if year:
            year_clause = "AND strftime('%Y', f.departure_datetime) = ?"
            params.append(str(year))

        with db_conn() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    f.flight_number, f.airline_code, f.airline_name,
                    f.departure_airport, f.arrival_airport,
                    f.departure_datetime, f.arrival_datetime,
                    f.duration_minutes,
                    dep.latitude  AS dep_lat,  dep.longitude AS dep_lon,
                    dep.city_name AS dep_city, dep.country_code AS dep_country,
                    arr.latitude  AS arr_lat,  arr.longitude AS arr_lon,
                    arr.city_name AS arr_city, arr.country_code AS arr_country,
                    t.name AS trip_name
                FROM flights f
                LEFT JOIN airports dep ON dep.iata_code = f.departure_airport
                LEFT JOIN airports arr ON arr.iata_code = f.arrival_airport
                LEFT JOIN trips t ON t.id = f.trip_id
                WHERE f.user_id = ? {year_clause}
                  AND f.arrival_datetime < datetime('now')
                ORDER BY f.departure_datetime
                """,
                params,
            ).fetchall()
        return [row_to_flight_stats_row(r) for r in rows]

    def list_years_with_flights(self, user_id: int) -> list[str]:
        with db_conn() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT strftime('%Y', departure_datetime) AS y
                FROM flights
                WHERE user_id = ? AND departure_datetime IS NOT NULL
                ORDER BY y DESC
                """,
                [user_id],
            ).fetchall()
        return [r["y"] for r in rows if r["y"]]

    def list_ground_countries(self, user_id: int, year: int | None = None) -> list[str]:
        """Country codes recorded on the user's completed ground legs and stays.

        Only countries — deliberately. Distance, hours and the flight count stay
        flight-only, so a train does not inflate "hours in air"; but being in
        Norway is being in Norway however you got there, which is the one thing
        a Stockholm-Oslo train genuinely proves.

        There is no layover rule here, unlike flights. Airside transit is the
        reason that rule exists — you can pass through an airport without
        entering the country. Changing trains puts you in the station, in the
        city, past no border fiction, so every endpoint counts.

        `trip_segments` and `trip_stays` have no `user_id`; they hang off a trip,
        so ownership comes from the join. Shared trips are excluded on purpose,
        matching `list_completed_flights`, which scopes to `f.user_id`.
        """
        # Three arms, each with the same (user_id[, year]) parameter shape.
        arms = [
            ("trip_segments", "departure_country", "arrival_datetime", "departure_datetime"),
            ("trip_segments", "arrival_country", "arrival_datetime", "departure_datetime"),
            ("trip_stays", "country", "check_out_datetime", "check_in_datetime"),
        ]
        selects: list[str] = []
        params: list = []
        for table, column, completed_col, year_col in arms:
            year_clause = f"AND strftime('%Y', s.{year_col}) = ?" if year else ""
            selects.append(
                f"""
                SELECT s.{column} AS c FROM {table} s
                  JOIN trips t ON t.id = s.trip_id
                 WHERE t.user_id = ? AND s.{column} IS NOT NULL
                   AND s.{completed_col} < datetime('now') {year_clause}
                """
            )
            params.append(user_id)
            if year:
                params.append(str(year))

        with db_conn() as conn:
            rows = conn.execute(" UNION ".join(selects), params).fetchall()
        return [r["c"] for r in rows if r["c"]]

    def count_ground_legs(self, user_id: int, year: int | None = None) -> int:
        """Completed train/bus/ferry/car legs, scoped like the flight query."""
        year_clause = "AND strftime('%Y', s.departure_datetime) = ?" if year else ""
        params: list = [user_id]
        if year:
            params.append(str(year))
        with db_conn() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS c FROM trip_segments s
                  JOIN trips t ON t.id = s.trip_id
                 WHERE t.user_id = ? AND s.arrival_datetime < datetime('now') {year_clause}
                """,
                params,
            ).fetchone()
        return row["c"] if row else 0

    def list_stay_night_ranges(
        self, user_id: int, year: int | None = None
    ) -> list[tuple[str, str]]:
        """(check_in_date, check_out_date) for completed stays.

        Ranges rather than a summed night count, because two overlapping stays
        are not two nights away — the service expands these into a set of dates
        so a night booked twice is still one night.
        """
        year_clause = "AND strftime('%Y', s.check_in_datetime) = ?" if year else ""
        params: list = [user_id]
        if year:
            params.append(str(year))
        with db_conn() as conn:
            rows = conn.execute(
                f"""
                SELECT s.check_in_date, s.check_out_date FROM trip_stays s
                  JOIN trips t ON t.id = s.trip_id
                 WHERE t.user_id = ? AND s.check_out_datetime < datetime('now') {year_clause}
                """,
                params,
            ).fetchall()
        return [(r["check_in_date"], r["check_out_date"]) for r in rows]
