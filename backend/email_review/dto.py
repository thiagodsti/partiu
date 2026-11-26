"""Request/response models for the email review API (routes.py)."""

from pydantic import BaseModel, Field


class HintsDTO(BaseModel):
    flight_numbers: list[str] = []
    airports: list[str] = []
    dates: list[str] = []
    times: list[str] = []
    booking_reference: str | None = None
    excerpt: list[str] = []


class CandidateDTO(BaseModel):
    id: str
    sender: str | None
    subject: str | None
    email_date: str | None
    hints: HintsDTO
    booking_reference: str | None


class CandidateListDTO(BaseModel):
    items: list[CandidateDTO]
    # Whether "Fill with AI" can be offered (Ollama configured).
    ai_available: bool


class CountDTO(BaseModel):
    count: int


class LegDTO(BaseModel):
    flight_number: str = Field(max_length=10)
    departure_airport: str = Field(max_length=3)
    arrival_airport: str = Field(max_length=3)
    # Local time at each airport, "YYYY-MM-DDTHH:MM".
    departure_datetime: str = Field(max_length=25)
    arrival_datetime: str = Field(max_length=25)
    booking_reference: str = Field("", max_length=50)


class DraftLegDTO(LegDTO):
    # Fields left empty because the email does not support the model's guess:
    # {field: what the model guessed}.
    doubts: dict[str, str] = {}


class DraftDTO(BaseModel):
    legs: list[DraftLegDTO]


class ImportRequestDTO(BaseModel):
    legs: list[LegDTO] = Field(max_length=20)


class ImportResultDTO(BaseModel):
    flight_ids: list[str]
    trip_ids: list[str]


class IgnoredSenderDTO(BaseModel):
    domain: str
    created_at: str


class IgnoreResultDTO(BaseModel):
    dismissed: int
