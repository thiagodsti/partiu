"""Use cases for flights: CRUD, listing/pagination, and ungrouping a flight
into its own solo trip.

CSV export and aircraft lookup are separate concerns — see export_service.py
and aircraft_service.py."""

import uuid
from datetime import datetime

from ..utils import (
    calc_duration_minutes,
    calc_flight_status,
    dt_to_iso,
    now_iso,
    validate_flight_number,
)
from .domain import Flight
from .errors import FlightError
from .repository import FlightRepository


class FlightService:
    def __init__(self, repository: FlightRepository | None = None):
        self._repository = repository or FlightRepository()

    # -- List / get ------------------------------------------------------------

    def list_flights(
        self,
        user_id: int,
        trip_id: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Flight], int]:
        if trip_id and not self._can_access_trip(trip_id, user_id):
            raise FlightError("Trip not found", 404)
        return self._repository.list_flights(user_id, trip_id, status, limit, offset)

    def get_flight(self, flight_id: str, user_id: int) -> Flight:
        if not self._can_access_flight(flight_id, user_id):
            raise FlightError("Flight not found", 404)
        flight = self._repository.get_by_id(flight_id)
        if flight is None:
            raise FlightError("Flight not found", 404)
        return flight

    def get_flight_email(self, flight_id: str, user_id: int) -> dict:
        if not self._can_access_flight(flight_id, user_id):
            raise FlightError("Flight not found", 404)
        row = self._repository.get_email_fields(flight_id)
        if row is None:
            raise FlightError("Flight not found", 404)
        return {
            "html_body": row["email_body"] or "",
            "email_subject": row["email_subject"] or "",
            "email_date": row["email_date"] or "",
        }

    # -- Create / update / delete --------------------------------------------

    def create_flight(self, user_id: int, body_fields: dict) -> str:
        """``body_fields`` mirrors FlightCreateDTO's fields. Returns the new flight id."""
        from ..airports.timezone import apply_airport_timezones
        from ..trips.repository import TripRepository

        flight_number = body_fields["flight_number"]
        if not validate_flight_number(flight_number):
            raise FlightError("Invalid flight number format", 422)

        now = now_iso()
        flight_id = str(uuid.uuid4())

        departure_datetime = body_fields["departure_datetime"]
        arrival_datetime = body_fields["arrival_datetime"]
        dep_obj = arr_obj = None
        try:
            dep_obj = datetime.fromisoformat(departure_datetime)
            arr_obj = datetime.fromisoformat(arrival_datetime)
        except (ValueError, TypeError):
            pass

        # Apply timezone lookup — converts local times to UTC (same as auto-synced flights)
        tz_info = apply_airport_timezones(
            {
                "departure_airport": body_fields["departure_airport"],
                "arrival_airport": body_fields["arrival_airport"],
                "departure_datetime": dep_obj,
                "arrival_datetime": arr_obj,
            }
        )
        departure_timezone = tz_info.get("departure_timezone")
        arrival_timezone = tz_info.get("arrival_timezone")

        # Use UTC-converted datetimes for storage so ORDER BY sorts correctly
        # alongside email-synced flights (which always store UTC).
        dep_utc = tz_info.get("departure_datetime")
        arr_utc = tz_info.get("arrival_datetime")
        dep_iso = dt_to_iso(dep_utc) if dep_utc is not None else departure_datetime
        arr_iso = dt_to_iso(arr_utc) if arr_utc is not None else arrival_datetime

        duration_minutes = calc_duration_minutes(dep_utc or dep_obj, arr_utc or arr_obj)

        trip_id = body_fields.get("trip_id")
        if trip_id:
            trip_repository = TripRepository()
            if not trip_repository.trip_owned_exists(trip_id, user_id):
                raise FlightError("Trip not found or access denied", 403)

        status = calc_flight_status(arr_utc or arr_obj)

        fields = {
            "trip_id": trip_id,
            "airline_name": body_fields["airline_name"],
            "airline_code": body_fields["airline_code"],
            "flight_number": flight_number,
            "booking_reference": body_fields["booking_reference"],
            "departure_airport": body_fields["departure_airport"],
            "departure_datetime": dep_iso,
            "departure_terminal": body_fields["departure_terminal"],
            "departure_gate": body_fields["departure_gate"],
            "arrival_airport": body_fields["arrival_airport"],
            "arrival_datetime": arr_iso,
            "arrival_terminal": body_fields["arrival_terminal"],
            "arrival_gate": body_fields["arrival_gate"],
            "passenger_name": body_fields["passenger_name"],
            "seat": body_fields["seat"],
            "cabin_class": body_fields["cabin_class"],
            "duration_minutes": duration_minutes,
            "status": status,
            "departure_timezone": departure_timezone,
            "arrival_timezone": arrival_timezone,
            "notes": body_fields["notes"],
        }
        self._repository.create(flight_id, fields, user_id, now)

        if trip_id:
            TripRepository().recompute_span(trip_id, now)

        return flight_id

    def update_flight(self, flight_id: str, user_id: int, body_fields: dict) -> None:
        """``body_fields`` mirrors FlightUpdateDTO's fields (only provided keys)."""
        from ..airports.timezone import apply_airport_timezones
        from ..trips.repository import TripRepository

        existing = self._repository.get_owned(flight_id, user_id)
        if existing is None:
            raise FlightError("Flight not found", 404)

        if body_fields.get("flight_number") is not None and not validate_flight_number(
            body_fields["flight_number"]
        ):
            raise FlightError("Invalid flight number format", 422)

        updates: dict = {}
        for field in (
            "flight_number",
            "airline_name",
            "airline_code",
            "booking_reference",
            "passenger_name",
            "seat",
            "cabin_class",
            "departure_terminal",
            "departure_gate",
            "arrival_terminal",
            "arrival_gate",
            "notes",
            "trip_id",
            "status",
        ):
            val = body_fields.get(field)
            if val is not None:
                updates[field] = val

        # When airports or datetimes change, re-run timezone conversion and recompute
        # duration/status so the stored datetimes stay in UTC format.
        times_changed = any(
            body_fields.get(f) is not None
            for f in (
                "departure_airport",
                "arrival_airport",
                "departure_datetime",
                "arrival_datetime",
            )
        )
        if times_changed:
            dep_airport = body_fields.get("departure_airport") or existing.departure_airport
            arr_airport = body_fields.get("arrival_airport") or existing.arrival_airport
            raw_dep = body_fields.get("departure_datetime") or existing.departure_datetime
            raw_arr = body_fields.get("arrival_datetime") or existing.arrival_datetime

            dep_obj = arr_obj = None
            try:
                dep_obj = datetime.fromisoformat(raw_dep)
            except (ValueError, TypeError):
                pass
            try:
                arr_obj = datetime.fromisoformat(raw_arr)
            except (ValueError, TypeError):
                pass

            tz_info = apply_airport_timezones(
                {
                    "departure_airport": dep_airport,
                    "arrival_airport": arr_airport,
                    "departure_datetime": dep_obj,
                    "arrival_datetime": arr_obj,
                }
            )
            dep_utc = tz_info.get("departure_datetime")
            arr_utc = tz_info.get("arrival_datetime")

            updates["departure_airport"] = dep_airport
            updates["arrival_airport"] = arr_airport
            updates["departure_datetime"] = dt_to_iso(dep_utc) if dep_utc is not None else raw_dep
            updates["arrival_datetime"] = dt_to_iso(arr_utc) if arr_utc is not None else raw_arr
            updates["departure_timezone"] = tz_info.get("departure_timezone")
            updates["arrival_timezone"] = tz_info.get("arrival_timezone")
            updates["duration_minutes"] = calc_duration_minutes(
                dep_utc or dep_obj, arr_utc or arr_obj
            )
            if body_fields.get("status") is None:
                updates["status"] = calc_flight_status(arr_utc or arr_obj)

        if not updates:
            return

        now = now_iso()
        updates["updated_at"] = now

        trip_id = updates.get("trip_id") or existing.trip_id

        self._repository.update(flight_id, user_id, updates)

        if trip_id and times_changed:
            TripRepository().recompute_span(trip_id, now)

    def delete_flight(self, flight_id: str, user_id: int) -> None:
        """Move the flight (and its boarding passes) to the trash — see `trash.service`."""
        existing = self._repository.get_owned(flight_id, user_id)
        if existing is None:
            raise FlightError("Flight not found", 404)
        from ..trash.service import trash_service

        trash_service.trash_flight(flight_id, user_id)

    # -- Ungroup ---------------------------------------------------------------

    def ungroup_flight(self, flight_id: str, user_id: int) -> str:
        """Move a flight out of its current trip into a new solo trip. Returns
        the new trip id."""
        import json

        from ..trips.repository import TripRepository

        flight = self._repository.get_owned(flight_id, user_id)
        if flight is None:
            raise FlightError("Flight not found", 404)
        if not flight.trip_id:
            raise FlightError("Flight is not part of a trip", 400)

        # Ensure the trip has more than one flight — no point ungrouping a solo flight
        count = self._repository.count_in_trip(flight.trip_id)
        if count <= 1:
            raise FlightError("Trip only has one flight; nothing to ungroup", 400)

        dep = flight.departure_airport or ""
        arr = flight.arrival_airport or ""
        trip_name = f"{dep} → {arr}" if dep and arr else flight.flight_number or "Flight"
        booking_ref = flight.booking_reference or ""
        start_date = str(flight.departure_datetime)[:10] if flight.departure_datetime else ""
        end_date = str(flight.arrival_datetime)[:10] if flight.arrival_datetime else ""

        now = now_iso()
        new_trip_id = str(uuid.uuid4())

        trip_repository = TripRepository()
        trip_repository.create(
            new_trip_id,
            trip_name,
            json.dumps([booking_ref] if booking_ref else []),
            start_date,
            end_date,
            dep,
            arr,
            user_id,
            now,
            is_auto_generated=True,
        )
        trip_repository.assign_flight(flight_id, new_trip_id, user_id, now)

        return new_trip_id

    # -- Access helpers -------------------------------------------------------

    def _can_access_trip(self, trip_id: str, user_id: int) -> bool:
        from ..auth import can_access_trip
        from ..database import db_conn

        with db_conn() as conn:
            return can_access_trip(trip_id, user_id, conn)

    def _can_access_flight(self, flight_id: str, user_id: int) -> bool:
        from ..auth import can_access_flight
        from ..database import db_conn

        with db_conn() as conn:
            return can_access_flight(flight_id, user_id, conn)


flight_service = FlightService()
