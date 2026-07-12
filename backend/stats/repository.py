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
