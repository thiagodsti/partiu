"""Domain objects for the travel-statistics feature."""

from dataclasses import dataclass


@dataclass
class FlightStatsRow:
    """One completed flight, joined with its airports' coordinates/city/country."""

    flight_number: str | None
    airline_code: str | None
    airline_name: str | None
    departure_airport: str | None
    arrival_airport: str | None
    departure_datetime: str | None
    arrival_datetime: str | None
    duration_minutes: int | None
    dep_lat: float | None
    dep_lon: float | None
    dep_city: str | None
    dep_country: str | None
    arr_lat: float | None
    arr_lon: float | None
    arr_city: str | None
    arr_country: str | None
    trip_name: str | None


@dataclass
class TopEntry:
    key: str
    count: int
    label: str | None = None


@dataclass
class PeriodCount:
    label: str
    count: int


@dataclass
class FlightBreakdownItem:
    route: str
    flight: str
    km: int
    co2_kg: float
    trip_name: str


@dataclass
class TravelStats:
    total_km: int
    total_co2_kg: float
    total_flights: int
    total_hours: float
    unique_airports: int
    unique_countries: int
    visited_countries: list[str]
    # Ground legs and nights are exact counts. There is deliberately no
    # ground *distance*: rail track runs well above the great-circle line
    # (Stockholm-Oslo is ~520km straight against ~600km of track), and an
    # estimate rendered as a statistic is the guess this page avoids.
    ground_legs: int
    nights_away: int
    earth_laps: float
    longest_flight_km: int
    longest_flight_route: str
    top_routes: list[TopEntry]
    top_airports: list[TopEntry]
    top_airlines: list[TopEntry]
    years: list[str]
    flights_by_period: list[PeriodCount]
    flight_breakdown: list[FlightBreakdownItem]
