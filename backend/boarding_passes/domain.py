"""Domain objects for the boarding-passes feature."""

from dataclasses import dataclass


@dataclass
class BoardingPass:
    id: str
    flight_id: str
    passenger_name: str | None
    seat: str | None
    image_path: str | None
    source_email_id: str | None
    source_page: int
    created_at: str


@dataclass
class TripBoardingPass:
    """A boarding pass enriched with its flight's route info, for the trip-wide view."""

    id: str
    flight_id: str
    passenger_name: str | None
    seat: str | None
    source_page: int
    created_at: str
    flight_number: str
    departure_airport: str
    arrival_airport: str
