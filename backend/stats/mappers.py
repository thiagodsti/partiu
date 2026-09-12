"""Conversions between SQL rows, domain objects and DTOs."""

import sqlite3

from .domain import FlightBreakdownItem, FlightStatsRow, PeriodCount, TopEntry, TravelStats
from .dto import FlightBreakdownItemDTO, PeriodCountDTO, TopEntryDTO, TravelStatsDTO


def row_to_flight_stats_row(row: sqlite3.Row) -> FlightStatsRow:
    return FlightStatsRow(
        flight_number=row["flight_number"],
        airline_code=row["airline_code"],
        airline_name=row["airline_name"],
        departure_airport=row["departure_airport"],
        arrival_airport=row["arrival_airport"],
        departure_datetime=row["departure_datetime"],
        arrival_datetime=row["arrival_datetime"],
        duration_minutes=row["duration_minutes"],
        dep_lat=row["dep_lat"],
        dep_lon=row["dep_lon"],
        dep_city=row["dep_city"],
        dep_country=row["dep_country"],
        arr_lat=row["arr_lat"],
        arr_lon=row["arr_lon"],
        arr_city=row["arr_city"],
        arr_country=row["arr_country"],
        trip_name=row["trip_name"],
    )


def _top_entry_to_dto(entry: TopEntry) -> TopEntryDTO:
    return TopEntryDTO(key=entry.key, count=entry.count, label=entry.label)


def _period_count_to_dto(period: PeriodCount) -> PeriodCountDTO:
    return PeriodCountDTO(label=period.label, count=period.count)


def _flight_breakdown_to_dto(item: FlightBreakdownItem) -> FlightBreakdownItemDTO:
    return FlightBreakdownItemDTO(
        route=item.route,
        flight=item.flight,
        km=item.km,
        co2_kg=item.co2_kg,
        trip_name=item.trip_name,
    )


def stats_to_dto(stats: TravelStats) -> TravelStatsDTO:
    return TravelStatsDTO(
        total_km=stats.total_km,
        total_co2_kg=stats.total_co2_kg,
        total_flights=stats.total_flights,
        total_hours=stats.total_hours,
        unique_airports=stats.unique_airports,
        unique_countries=stats.unique_countries,
        visited_countries=stats.visited_countries,
        ground_legs=stats.ground_legs,
        nights_away=stats.nights_away,
        earth_laps=stats.earth_laps,
        longest_flight_km=stats.longest_flight_km,
        longest_flight_route=stats.longest_flight_route,
        top_routes=[_top_entry_to_dto(e) for e in stats.top_routes],
        top_airports=[_top_entry_to_dto(e) for e in stats.top_airports],
        top_airlines=[_top_entry_to_dto(e) for e in stats.top_airlines],
        years=stats.years,
        flights_by_period=[_period_count_to_dto(p) for p in stats.flights_by_period],
        flight_breakdown=[_flight_breakdown_to_dto(f) for f in stats.flight_breakdown],
    )
