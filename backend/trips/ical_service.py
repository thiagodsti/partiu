"""Builds the iCalendar (.ics) export for a trip — a self-contained concern
kept out of service.py (which owns trip CRUD, not calendar formatting)."""

from datetime import UTC, datetime

from .errors import TripError
from .repository import TripRepository


class IcalService:
    def __init__(self, repository: TripRepository | None = None):
        self._repository = repository or TripRepository()

    def export_ical(self, trip_id: str, user_id: int) -> tuple[str, str]:
        """Return (ics_content, filename)."""
        if not self._can_access(trip_id, user_id):
            raise TripError("Trip not found", 404)

        trip = self._repository.get_by_id(trip_id)
        if trip is None:
            raise TripError("Trip not found", 404)

        flights = self._repository.get_flights_for_trip(trip_id)

        now_utc = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        trip_name = trip.name or "Trip"
        safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in trip_name).strip()

        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Partiu//Trip Export//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            f"X-WR-CALNAME:{trip_name}",
        ]

        def _to_ical_dt(dt_str: str) -> str:
            try:
                dt = datetime.fromisoformat(dt_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
            except (ValueError, TypeError):
                return now_utc

        # Add a single span event covering the full trip (timed, not all-day, for broad client support)
        dep_dates = [f["departure_datetime"] for f in flights if f["departure_datetime"]]
        arr_dates = [f["arrival_datetime"] for f in flights if f["arrival_datetime"]]
        all_dates = dep_dates + arr_dates
        if all_dates:
            try:
                first_dt = min(datetime.fromisoformat(d) for d in all_dates)
                last_dt = max(datetime.fromisoformat(d) for d in all_dates)
                if first_dt.tzinfo is None:
                    first_dt = first_dt.replace(tzinfo=UTC)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=UTC)
                span_start = first_dt.astimezone(UTC).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                span_end = last_dt.astimezone(UTC).replace(
                    hour=23, minute=59, second=59, microsecond=0
                )
                span_start_ical = span_start.strftime("%Y%m%dT%H%M%SZ")
                span_end_ical = span_end.strftime("%Y%m%dT%H%M%SZ")
                lines += [
                    "BEGIN:VEVENT",
                    f"UID:{trip_id}-span@partiu",
                    f"DTSTAMP:{now_utc}",
                    f"DTSTART:{span_start_ical}",
                    f"DTEND:{span_end_ical}",
                    f"SUMMARY:{trip_name}",
                    "TRANSP:TRANSPARENT",
                    "END:VEVENT",
                ]
            except (ValueError, TypeError):
                pass

        for flight in flights:
            dep_str = flight["departure_datetime"]
            arr_str = flight["arrival_datetime"]

            dep_ical = _to_ical_dt(dep_str) if dep_str else now_utc
            arr_ical = _to_ical_dt(arr_str) if arr_str else now_utc

            flight_number = flight["flight_number"] or ""
            dep_airport = flight["departure_airport"] or ""
            arr_airport = flight["arrival_airport"] or ""
            booking_ref = flight["booking_reference"] or ""
            seat = flight["seat"] or ""
            cabin = flight["cabin_class"] or ""
            aircraft = flight["aircraft_type"] or ""
            passenger = flight["passenger_name"] or ""

            summary = f"{flight_number}: {dep_airport} → {arr_airport}"

            desc_parts = []
            if booking_ref:
                desc_parts.append(f"Booking Ref: {booking_ref}")
            if passenger:
                desc_parts.append(f"Passenger: {passenger}")
            if seat:
                desc_parts.append(f"Seat: {seat}")
            if cabin:
                desc_parts.append(f"Class: {cabin}")
            if aircraft:
                desc_parts.append(f"Aircraft: {aircraft}")
            description = "\\n".join(desc_parts)

            uid = f"{flight['id']}@partiu"

            lines += [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{now_utc}",
                f"DTSTART:{dep_ical}",
                f"DTEND:{arr_ical}",
                f"SUMMARY:{summary}",
                f"LOCATION:{dep_airport} → {arr_airport}",
            ]
            if description:
                lines.append(f"DESCRIPTION:{description}")
            lines += [
                "BEGIN:VALARM",
                "TRIGGER:-PT1H",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{flight_number} departs in 1 hour",
                "END:VALARM",
            ]
            lines.append("END:VEVENT")

        lines.append("END:VCALENDAR")

        content = "\r\n".join(lines) + "\r\n"
        filename = f"{safe_name or trip_id}.ics"
        return content, filename

    def _can_access(self, trip_id: str, user_id: int) -> bool:
        from ..auth import can_access_trip
        from ..database import db_conn

        with db_conn() as conn:
            return can_access_trip(trip_id, user_id, conn)


ical_service = IcalService()
