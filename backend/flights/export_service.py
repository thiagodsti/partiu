"""CSV export of completed flights — a distinct concern from flight CRUD,
kept out of service.py."""

import csv
import io
import math

from .repository import FlightRepository

_CO2_FACTOR_SHORT = 0.255
_CO2_FACTOR_LONG = 0.195


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlam = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _sanitize_csv_cell(value: str) -> str:
    """Prefix formula-trigger characters to prevent spreadsheet injection."""
    if value and value[0] in ("=", "+", "-", "@"):
        return "'" + value
    return value


class FlightExportService:
    def __init__(self, repository: FlightRepository | None = None):
        self._repository = repository or FlightRepository()

    def export_csv(self, user_id: int) -> str:
        """Download all completed flights as a CSV file."""
        rows = self._repository.list_for_export(user_id)

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "Date",
                "Flight",
                "Airline",
                "From (IATA)",
                "From City",
                "From Country",
                "To (IATA)",
                "To City",
                "To Country",
                "Distance (km)",
                "CO2 (kg)",
                "Duration (min)",
                "Seat",
                "Aircraft",
                "Booking Ref",
                "Trip",
            ]
        )
        for r in rows:
            km = 0
            co2 = 0.0
            if all(r[k] is not None for k in ("dep_lat", "dep_lon", "arr_lat", "arr_lon")):
                km = round(_haversine(r["dep_lat"], r["dep_lon"], r["arr_lat"], r["arr_lon"]))
                factor = _CO2_FACTOR_SHORT if km <= 3000 else _CO2_FACTOR_LONG
                co2 = round(km * factor, 1)
            date = (r["departure_datetime"] or "")[:10]
            writer.writerow(
                [
                    date,
                    _sanitize_csv_cell(r["flight_number"] or ""),
                    _sanitize_csv_cell(r["airline_name"] or r["airline_code"] or ""),
                    _sanitize_csv_cell(r["departure_airport"] or ""),
                    _sanitize_csv_cell(r["dep_city"] or ""),
                    _sanitize_csv_cell(r["dep_country"] or ""),
                    _sanitize_csv_cell(r["arrival_airport"] or ""),
                    _sanitize_csv_cell(r["arr_city"] or ""),
                    _sanitize_csv_cell(r["arr_country"] or ""),
                    km or "",
                    co2 or "",
                    r["duration_minutes"] or "",
                    _sanitize_csv_cell(r["seat"] or ""),
                    _sanitize_csv_cell(r["aircraft_type"] or ""),
                    _sanitize_csv_cell(r["booking_reference"] or ""),
                    _sanitize_csv_cell(r["trip_name"] or ""),
                ]
            )

        return buf.getvalue()


flight_export_service = FlightExportService()
