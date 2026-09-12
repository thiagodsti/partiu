"""Response DTOs for the travel-statistics HTTP API (routes.py)."""

from pydantic import BaseModel


class TopEntryDTO(BaseModel):
    key: str
    count: int
    label: str | None = None


class PeriodCountDTO(BaseModel):
    label: str
    count: int


class FlightBreakdownItemDTO(BaseModel):
    route: str
    flight: str
    km: int
    co2_kg: float
    trip_name: str


class TravelStatsDTO(BaseModel):
    total_km: int
    total_co2_kg: float
    total_flights: int
    total_hours: float
    unique_airports: int
    unique_countries: int
    visited_countries: list[str]
    ground_legs: int
    nights_away: int
    earth_laps: float
    longest_flight_km: int
    longest_flight_route: str
    top_routes: list[TopEntryDTO]
    top_airports: list[TopEntryDTO]
    top_airlines: list[TopEntryDTO]
    years: list[str]
    flights_by_period: list[PeriodCountDTO]
    flight_breakdown: list[FlightBreakdownItemDTO]
