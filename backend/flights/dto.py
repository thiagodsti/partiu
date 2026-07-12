"""Request/response DTOs for the flights HTTP API (routes.py).

FlightDTO mirrors the `flights` table 1:1 (43 columns), matching the original
route's unfiltered ``dict(row)`` response shape exactly. The aircraft-info
endpoint deliberately has no response_model — its shape comes from an external
module (backend.integrations.aircraft.client) that this refactor doesn't touch.
"""

from pydantic import BaseModel, Field


class FlightDTO(BaseModel):
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


class FlightListResponseDTO(BaseModel):
    flights: list[FlightDTO]
    total: int
    limit: int
    offset: int


class FlightCreateDTO(BaseModel):
    flight_number: str
    airline_name: str = ""
    airline_code: str = ""
    departure_airport: str
    departure_datetime: str
    arrival_airport: str
    arrival_datetime: str
    booking_reference: str = ""
    passenger_name: str = ""
    seat: str = ""
    cabin_class: str = ""
    departure_terminal: str = ""
    departure_gate: str = ""
    arrival_terminal: str = ""
    arrival_gate: str = ""
    notes: str = Field("", max_length=10000)
    trip_id: str | None = None


class FlightUpdateDTO(BaseModel):
    flight_number: str | None = None
    airline_name: str | None = None
    airline_code: str | None = None
    departure_airport: str | None = None
    departure_datetime: str | None = None
    arrival_airport: str | None = None
    arrival_datetime: str | None = None
    booking_reference: str | None = None
    passenger_name: str | None = None
    seat: str | None = None
    cabin_class: str | None = None
    departure_terminal: str | None = None
    departure_gate: str | None = None
    arrival_terminal: str | None = None
    arrival_gate: str | None = None
    notes: str | None = Field(None, max_length=10000)
    trip_id: str | None = None
    status: str | None = None


class FlightIdResponseDTO(BaseModel):
    id: str


class EmailBodyDTO(BaseModel):
    html_body: str
    email_subject: str
    email_date: str


class UngroupResponseDTO(BaseModel):
    trip_id: str
