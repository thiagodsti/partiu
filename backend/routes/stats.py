"""
Travel statistics endpoint.
"""

import math
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends

from ..auth import get_current_user
from ..database import db_conn

router = APIRouter(prefix="/api/stats", tags=["stats"])

EARTH_CIRCUMFERENCE_KM = 40_075


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    R = 6_371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@router.get("")
def get_stats(year: int | None = None, user: dict = Depends(get_current_user)):
    """Return travel statistics for the current user, optionally filtered by year."""
    with db_conn() as conn:
        year_clause = ""
        base_params: list = [user["id"]]
        if year:
            year_clause = "AND strftime('%Y', f.departure_datetime) = ?"
            base_params.append(str(year))

        rows = conn.execute(
            f"""
            SELECT
                f.flight_number, f.airline_code,
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
            base_params,
        ).fetchall()

        year_rows = conn.execute(
            """
            SELECT DISTINCT strftime('%Y', departure_datetime) AS y
            FROM flights
            WHERE user_id = ? AND departure_datetime IS NOT NULL
            ORDER BY y DESC
            """,
            [user["id"]],
        ).fetchall()

    total_km = 0.0
    total_minutes = 0
    airports: set[str] = set()
    countries: set[str] = set()
    route_counts: dict[str, int] = defaultdict(int)
    airport_counts: dict[str, int] = defaultdict(int)
    airline_counts: dict[str, int] = defaultdict(int)
    longest_flight_km = 0.0
    longest_flight_route = ""
    flight_breakdown: list[dict] = []

    for r in rows:
        dep = r["departure_airport"]
        arr = r["arrival_airport"]

        # Distance
        flight_km = 0.0
        if all(r[k] is not None for k in ("dep_lat", "dep_lon", "arr_lat", "arr_lon")):
            flight_km = _haversine(r["dep_lat"], r["dep_lon"], r["arr_lat"], r["arr_lon"])
            total_km += flight_km
            if flight_km > longest_flight_km:
                longest_flight_km = flight_km
                longest_flight_route = f"{dep}→{arr}" if dep and arr else ""

        flight_breakdown.append(
            {
                "route": f"{dep}→{arr}" if dep and arr else f"{dep or '?'}→{arr or '?'}",
                "flight": r["flight_number"] or "",
                "km": round(flight_km),
                "trip_name": r["trip_name"] or "",
            }
        )

        if r["duration_minutes"]:
            total_minutes += r["duration_minutes"]

        for code in (dep, arr):
            if code:
                airports.add(code)
                airport_counts[code] += 1

        if dep and arr:
            route_counts[f"{dep}→{arr}"] += 1

        if r["airline_code"]:
            airline_counts[r["airline_code"]] += 1

    # Visited countries: first departure + last arrival always count.
    # Middle stops count only if the layover in that country is >= 24h.
    LAYOVER_THRESHOLD = timedelta(hours=24)

    def _parse_dt(s: str | None) -> datetime | None:
        if not s:
            return None
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

    for i, r in enumerate(rows):
        dep_country = r["dep_country"]
        arr_country = r["arr_country"]

        # First flight: departure country always counts
        if i == 0 and dep_country:
            countries.add(dep_country)

        # Last flight: arrival country always counts
        if i == len(rows) - 1 and arr_country:
            countries.add(arr_country)

        # Middle arrivals: count only if next departure from same country is >= 24h later
        if i < len(rows) - 1 and arr_country:
            nxt = rows[i + 1]
            if nxt["dep_country"] == arr_country:
                arr_dt = _parse_dt(r["arrival_datetime"])
                dep_dt = _parse_dt(nxt["departure_datetime"])
                if arr_dt and dep_dt and (dep_dt - arr_dt) >= LAYOVER_THRESHOLD:
                    countries.add(arr_country)
            else:
                # Next flight departs from a different country → this was a real stop
                countries.add(arr_country)

        # Middle departures: count only if previous arrival in same country was >= 24h ago
        if i > 0 and dep_country:
            prev = rows[i - 1]
            if prev["arr_country"] == dep_country:
                prev_arr_dt = _parse_dt(prev["arrival_datetime"])
                dep_dt = _parse_dt(r["departure_datetime"])
                if prev_arr_dt and dep_dt and (dep_dt - prev_arr_dt) >= LAYOVER_THRESHOLD:
                    countries.add(dep_country)
            else:
                # Previous flight arrived from a different country → fresh start here
                countries.add(dep_country)

    def top(d: dict, n: int = 5) -> list[dict]:
        return [
            {"key": k, "count": v}
            for k, v in sorted(d.items(), key=lambda x: x[1], reverse=True)[:n]
        ]

    return {
        "total_km": round(total_km),
        "total_flights": len(rows),
        "total_hours": round(total_minutes / 60, 1),
        "unique_airports": len(airports),
        "unique_countries": len(countries),
        "visited_countries": sorted(countries),
        "earth_laps": round(total_km / EARTH_CIRCUMFERENCE_KM, 2),
        "longest_flight_km": round(longest_flight_km),
        "longest_flight_route": longest_flight_route,
        "top_routes": top(route_counts),
        "top_airports": top(airport_counts),
        "top_airlines": top(airline_counts),
        "years": [r["y"] for r in year_rows if r["y"]],
        "flight_breakdown": flight_breakdown,
    }
