"""Domain object for the flights feature.

Field set mirrors the `flights` table 1:1 (43 columns) — the original routes
returned ``dict(row)`` unfiltered, so this preserves that contract exactly.
"""

from dataclasses import dataclass


@dataclass
class Flight:
    id: str
    trip_id: str | None
    airline_name: str | None
    airline_code: str | None
    flight_number: str
    booking_reference: str | None
    departure_airport: str
    departure_datetime: str
    departure_terminal: str | None
    departure_gate: str | None
    arrival_airport: str
    arrival_datetime: str
    arrival_terminal: str | None
    arrival_gate: str | None
    passenger_name: str | None
    seat: str | None
    cabin_class: str | None
    duration_minutes: int | None
    status: str
    departure_timezone: str | None
    arrival_timezone: str | None
    email_message_id: str | None
    email_subject: str | None
    email_date: str | None
    aircraft_type: str | None
    aircraft_icao: str | None
    aircraft_fetched_at: str | None
    is_manually_added: int
    notes: str | None
    created_at: str
    updated_at: str
    email_body: str | None
    aircraft_registration: str | None
    user_id: int | None
    aircraft_fetch_attempts: int
    aircraft_next_retry_at: str | None
    live_status: str | None
    live_departure_delay: int | None
    live_arrival_delay: int | None
    live_departure_actual: str | None
    live_arrival_estimated: str | None
    live_status_fetched_at: str | None
    aircraft_confirmed: int
