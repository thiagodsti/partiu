"""Computes travel statistics: distance/CO2, top routes/airports/airlines, visited
countries (with the 24h-layover rule), and period bucketing for the chart."""

import math
from collections import defaultdict
from datetime import datetime, timedelta

from .domain import FlightBreakdownItem, PeriodCount, TopEntry, TravelStats
from .repository import StatsRepository

EARTH_CIRCUMFERENCE_KM = 40_075

# ICAO-inspired CO₂e emission factors per passenger-km (economy, includes RFI)
_CO2_FACTOR_SHORT = 0.255  # flights ≤ 3 000 km
_CO2_FACTOR_LONG = 0.195  # flights  > 3 000 km

_LAYOVER_THRESHOLD = timedelta(hours=24)


def _dedupe(rows: list) -> list:
    """Collapse rows describing the same leg twice.

    Nobody flies the same route at the same minute twice, so a second row with
    an identical route and identical times is a parsing artefact, not a flight.
    They do occur: a SAS confirmation prints "SK4698 | Airbus A320neo" and has
    been read as two legs, one of them numbered `A320`.

    Leaving them in was not only a doubled distance and a doubled CO2 figure —
    the phantom sat *between* the two halves of a connection and broke the
    adjacency the layover rule below depends on, so a 1h05 change of planes in
    Oslo counted as having visited Norway.
    """
    seen: set[tuple] = set()
    out = []
    for r in rows:
        key = (r.departure_airport, r.arrival_airport, r.departure_datetime, r.arrival_datetime)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    R = 6_371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _co2_kg(distance_km: float) -> float:
    factor = _CO2_FACTOR_SHORT if distance_km <= 3_000 else _CO2_FACTOR_LONG
    return round(distance_km * factor, 1)


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _top(
    counts: dict[str, int], n: int = 5, labels: dict[str, str] | None = None
) -> list[TopEntry]:
    return [
        TopEntry(key=k, count=v, label=(labels or {}).get(k))
        for k, v in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:n]
    ]


class StatsService:
    def __init__(self, repository: StatsRepository | None = None):
        self._repository = repository or StatsRepository()

    def compute_stats(self, user_id: int, year: int | None = None) -> TravelStats:
        rows = _dedupe(self._repository.list_completed_flights(user_id, year))
        years = self._repository.list_years_with_flights(user_id)
        ground_countries = self._repository.list_ground_countries(user_id, year)
        ground_legs = self._repository.count_ground_legs(user_id, year)
        nights_away = _count_distinct_nights(self._repository.list_stay_night_ranges(user_id, year))

        total_km = 0.0
        total_co2_kg = 0.0
        total_minutes = 0
        airports: set[str] = set()
        countries: set[str] = set()
        route_counts: dict[str, int] = defaultdict(int)
        airport_counts: dict[str, int] = defaultdict(int)
        airline_counts: dict[str, int] = defaultdict(int)
        airline_names: dict[str, str] = {}
        period_counts: dict[str, int] = defaultdict(int)
        longest_flight_km = 0.0
        longest_flight_route = ""
        flight_breakdown: list[FlightBreakdownItem] = []

        for r in rows:
            dep = r.departure_airport
            arr = r.arrival_airport

            flight_km = 0.0
            flight_co2 = 0.0
            if (
                r.dep_lat is not None
                and r.dep_lon is not None
                and r.arr_lat is not None
                and r.arr_lon is not None
            ):
                flight_km = _haversine(r.dep_lat, r.dep_lon, r.arr_lat, r.arr_lon)
                flight_co2 = _co2_kg(flight_km)
                total_km += flight_km
                total_co2_kg += flight_co2
                if flight_km > longest_flight_km:
                    longest_flight_km = flight_km
                    longest_flight_route = f"{dep}→{arr}" if dep and arr else ""

            flight_breakdown.append(
                FlightBreakdownItem(
                    route=f"{dep}→{arr}" if dep and arr else f"{dep or '?'}→{arr or '?'}",
                    flight=r.flight_number or "",
                    km=round(flight_km),
                    co2_kg=flight_co2,
                    trip_name=r.trip_name or "",
                )
            )

            if r.duration_minutes:
                total_minutes += r.duration_minutes

            for code in (dep, arr):
                if code:
                    airports.add(code)
                    airport_counts[code] += 1

            if dep and arr:
                route_counts[f"{dep}→{arr}"] += 1

            if r.airline_code:
                airline_counts[r.airline_code] += 1
                if r.airline_name:
                    airline_names[r.airline_code] = r.airline_name

            # Period bucketing: monthly when a year is selected, yearly otherwise
            if r.departure_datetime:
                period_key = r.departure_datetime[:7] if year else r.departure_datetime[:4]
                period_counts[period_key] += 1

        # Build flights_by_period
        if year:
            # Always emit all 12 months so the chart has a fixed x-axis
            flights_by_period = [
                PeriodCount(label=f"{year}-{m:02d}", count=period_counts.get(f"{year}-{m:02d}", 0))
                for m in range(1, 13)
            ]
        else:
            flights_by_period = [
                PeriodCount(label=k, count=v) for k, v in sorted(period_counts.items())
            ]

        # Visited countries: first departure + last arrival always count.
        # Middle stops count only if the layover in that country is >= 24h.
        for i, r in enumerate(rows):
            dep_country = r.dep_country
            arr_country = r.arr_country

            if i == 0 and dep_country:
                countries.add(dep_country)

            if i == len(rows) - 1 and arr_country:
                countries.add(arr_country)

            if i < len(rows) - 1 and arr_country:
                nxt = rows[i + 1]
                if nxt.dep_country == arr_country:
                    arr_dt = _parse_dt(r.arrival_datetime)
                    dep_dt_parsed = _parse_dt(nxt.departure_datetime)
                    if arr_dt and dep_dt_parsed and (dep_dt_parsed - arr_dt) >= _LAYOVER_THRESHOLD:
                        countries.add(arr_country)
                else:
                    countries.add(arr_country)

            if i > 0 and dep_country:
                prev = rows[i - 1]
                if prev.arr_country == dep_country:
                    prev_arr_dt = _parse_dt(prev.arrival_datetime)
                    dep_dt_parsed = _parse_dt(r.departure_datetime)
                    if (
                        prev_arr_dt
                        and dep_dt_parsed
                        and (dep_dt_parsed - prev_arr_dt) >= _LAYOVER_THRESHOLD
                    ):
                        countries.add(dep_country)
                else:
                    countries.add(dep_country)

        # Ground legs and stays contribute countries but nothing else: a train
        # to Oslo proves Norway just as well as a flight does, while counting it
        # in "hours in air" or the flight tally would be a lie. No layover rule
        # applies — see StatsRepository.list_ground_countries.
        countries.update(ground_countries)

        return TravelStats(
            total_km=round(total_km),
            total_co2_kg=round(total_co2_kg, 1),
            total_flights=len(rows),
            total_hours=round(total_minutes / 60, 1),
            unique_airports=len(airports),
            unique_countries=len(countries),
            visited_countries=sorted(countries),
            ground_legs=ground_legs,
            nights_away=nights_away,
            earth_laps=round(total_km / EARTH_CIRCUMFERENCE_KM, 2),
            longest_flight_km=round(longest_flight_km),
            longest_flight_route=longest_flight_route,
            top_routes=_top(route_counts),
            top_airports=_top(airport_counts),
            top_airlines=_top(airline_counts, labels=airline_names),
            years=years,
            flights_by_period=flights_by_period,
            flight_breakdown=flight_breakdown,
        )


stats_service = StatsService()


def _count_distinct_nights(ranges: list[tuple[str, str]]) -> int:
    """Nights covered by at least one stay.

    A union of dates rather than a sum of each stay's nights: overlapping
    bookings (a hotel held over a night also spent in an apartment, or two
    rooms on the same night) are still one night away. A stay covers the night
    of every date from check-in up to but excluding check-out — you leave on
    the check-out morning — which is the same rule the day planner bands on.
    """
    from datetime import date, timedelta

    nights: set[date] = set()
    for check_in, check_out in ranges:
        try:
            start = date.fromisoformat(check_in)
            end = date.fromisoformat(check_out)
        except (TypeError, ValueError):
            continue
        day = start
        while day < end:
            nights.add(day)
            day += timedelta(days=1)
    return len(nights)
