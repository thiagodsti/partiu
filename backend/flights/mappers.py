"""Conversions between SQL rows, domain objects and DTOs."""

import sqlite3

from .domain import Flight
from .dto import FlightDTO


def row_to_flight(row: sqlite3.Row) -> Flight:
    return Flight(
        id=row["id"],
        trip_id=row["trip_id"],
        airline_name=row["airline_name"],
        airline_code=row["airline_code"],
        flight_number=row["flight_number"],
        booking_reference=row["booking_reference"],
        departure_airport=row["departure_airport"],
        departure_datetime=row["departure_datetime"],
        departure_terminal=row["departure_terminal"],
        departure_gate=row["departure_gate"],
        arrival_airport=row["arrival_airport"],
        arrival_datetime=row["arrival_datetime"],
        arrival_terminal=row["arrival_terminal"],
        arrival_gate=row["arrival_gate"],
        passenger_name=row["passenger_name"],
        seat=row["seat"],
        cabin_class=row["cabin_class"],
        duration_minutes=row["duration_minutes"],
        status=row["status"],
        departure_timezone=row["departure_timezone"],
        arrival_timezone=row["arrival_timezone"],
        email_message_id=row["email_message_id"],
        email_subject=row["email_subject"],
        email_date=row["email_date"],
        aircraft_type=row["aircraft_type"],
        aircraft_icao=row["aircraft_icao"],
        aircraft_fetched_at=row["aircraft_fetched_at"],
        is_manually_added=row["is_manually_added"],
        notes=row["notes"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        email_body=row["email_body"],
        aircraft_registration=row["aircraft_registration"],
        user_id=row["user_id"],
        aircraft_fetch_attempts=row["aircraft_fetch_attempts"],
        aircraft_next_retry_at=row["aircraft_next_retry_at"],
        live_status=row["live_status"],
        live_departure_delay=row["live_departure_delay"],
        live_arrival_delay=row["live_arrival_delay"],
        live_departure_actual=row["live_departure_actual"],
        live_arrival_estimated=row["live_arrival_estimated"],
        live_status_fetched_at=row["live_status_fetched_at"],
        aircraft_confirmed=row["aircraft_confirmed"],
    )


def flight_to_dto(flight: Flight) -> FlightDTO:
    return FlightDTO(**flight.__dict__)
