"""Response DTOs for the boarding-passes HTTP API (routes.py).

Upload/delete/image-serving are file-based, not JSON-body requests, so there are no
request DTOs here — routes.py reads the raw UploadFile/path params directly.
"""

from pydantic import BaseModel


class BoardingPassDTO(BaseModel):
    id: str
    flight_id: str
    passenger_name: str | None
    seat: str | None
    source_page: int
    created_at: str


class TripBoardingPassDTO(BaseModel):
    id: str
    flight_id: str
    passenger_name: str | None
    seat: str | None
    source_page: int
    created_at: str
    flight_number: str
    departure_airport: str
    arrival_airport: str


class UploadResponseDTO(BaseModel):
    id: str
