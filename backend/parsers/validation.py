"""Plausibility gate applied to every extracted itinerary before it is stored.

Extraction is heuristic: rules, generic scanners and the LLM fallback all guess,
and a wrong guess used to be indistinguishable from a right one once it reached
the database.  The checks here are the cheap, physical ones a human would apply
at a glance — an airport code that isn't where the ticket says, a leg that would
need a supersonic aircraft, an arrival before its departure.

The guiding rule is that **dropping a leg beats storing a wrong one**: a missing
flight is visible to the user and re-importable, while a silently wrong one is
neither.  Every drop is logged with its reason so failures stay diagnosable.

Runs after ``apply_airport_timezones`` so the datetimes are true UTC — the same
check against naive local times would have to tolerate a ±14 h timezone spread
and would catch almost nothing.
"""

import logging
from datetime import timedelta

from .shared import _airport_distance

logger = logging.getLogger(__name__)

# No airliner in service cruises near this. Concorde managed ~2,150 km/h; the
# bound is deliberately well above subsonic block speeds (typically 700–900 km/h
# including taxi and climb) so only genuinely impossible legs are rejected.
MAX_PLAUSIBLE_SPEED_KMH = 1200.0

# Below this distance the speed test is meaningless — taxi and holding dominate,
# and a 60 km hop can legitimately be blocked at an hour.
MIN_DISTANCE_FOR_SPEED_CHECK_KM = 300.0

MAX_FLIGHT_DURATION = timedelta(hours=20)  # longest scheduled flights are ~19 h
MIN_FLIGHT_DURATION = timedelta(minutes=15)

# How far a leg must fall behind its predecessor before a missing year is the
# likeliest explanation. A genuine year-less date is out by months.
BACKWARDS_GAP_FOR_YEAR_ROLL = timedelta(days=2)


def _reject_reason(flight: dict) -> str | None:
    """Return why this leg is implausible, or None when it looks sound."""
    dep = (flight.get("departure_airport") or "").upper()
    arr = (flight.get("arrival_airport") or "").upper()
    dep_dt = flight.get("departure_datetime")
    arr_dt = flight.get("arrival_datetime")

    if not dep or not arr:
        return "missing airport code"
    if dep == arr:
        return f"departure and arrival are both {dep}"
    if not dep_dt or not arr_dt:
        return "missing departure or arrival time"

    duration = arr_dt - dep_dt
    if duration <= timedelta(0):
        return f"arrival {arr_dt} is not after departure {dep_dt}"
    if duration < MIN_FLIGHT_DURATION:
        return f"implausibly short flight ({duration})"
    if duration > MAX_FLIGHT_DURATION:
        return f"implausibly long flight ({duration})"

    distance = _airport_distance(dep, arr)
    # _airport_distance returns 1.0 when either airport is missing coordinates;
    # there is nothing to check in that case.
    if distance > MIN_DISTANCE_FOR_SPEED_CHECK_KM:
        hours = duration.total_seconds() / 3600
        speed = distance / hours if hours else float("inf")
        if speed > MAX_PLAUSIBLE_SPEED_KMH:
            return (
                f"{dep}->{arr} is {distance:.0f} km in {duration} "
                f"({speed:.0f} km/h — faster than any airliner)"
            )
    return None


def normalise_itinerary_years(flights: list[dict]) -> list[dict]:
    """Roll year-less dates forward so an itinerary never travels backwards.

    Confirmation emails routinely print departure dates without a year ("Fri,
    15 Jan"), and extractors fill in the year the email was sent.  For a return
    leg that crosses New Year, that is wrong by a year: a trip departing
    22 Dec 2026 came back on 15 Jan **2027**, not 15 Jan 2026.

    Rather than guessing from the email's own date — which breaks for
    after-the-fact emails about past flights — this only uses the itinerary's
    internal consistency: legs are listed in travel order, so a leg dated before
    the one preceding it must belong to the following year.  Legs are mutated in
    place and the list is returned for convenience.
    """
    previous_dep = None
    for flight in flights:
        dep_dt = flight.get("departure_datetime")
        arr_dt = flight.get("arrival_datetime")
        if not dep_dt:
            continue

        # Only a substantial step backwards indicates a missing year. Legs a few
        # hours out of order point at a misparse, and rolling those forward by a
        # whole year would turn a small error into a large one.
        if previous_dep is not None and (previous_dep - dep_dt) > BACKWARDS_GAP_FOR_YEAR_ROLL:
            shift = 0
            shifted = dep_dt
            # More than one year is never a rounding artefact of a missing year
            while shifted < previous_dep and shift < 2:
                shift += 1
                shifted = dep_dt.replace(year=dep_dt.year + shift)
            if shifted >= previous_dep:
                logger.info(
                    "Rolling %s forward %d year(s): %s -> %s (previous leg departs %s)",
                    flight.get("flight_number", "?"),
                    shift,
                    dep_dt.date(),
                    shifted.date(),
                    previous_dep.date(),
                )
                flight["departure_datetime"] = shifted
                if arr_dt:
                    flight["arrival_datetime"] = arr_dt.replace(year=arr_dt.year + shift)
                dep_dt = shifted

        previous_dep = dep_dt
    return flights


def check_route_continuity(flights: list[dict]) -> list[str]:
    """Report legs of one booking that do not chain onto the previous leg.

    A ticketed itinerary connects: you arrive where the next leg departs, unless
    the traveller moves between airports themselves. A break is a strong hint
    that an airport was resolved wrongly, so it is worth surfacing — but it is
    *reported*, not enforced, because open-jaw and surface-sector itineraries
    are perfectly legitimate.
    """
    warnings: list[str] = []
    by_ref: dict[str, list[dict]] = {}
    for flight in flights:
        ref = flight.get("booking_reference") or ""
        if ref:
            by_ref.setdefault(ref, []).append(flight)

    for ref, legs in by_ref.items():
        ordered = sorted(legs, key=lambda f: f.get("departure_datetime") or "")
        for previous, following in zip(ordered, ordered[1:], strict=False):
            if previous.get("arrival_airport") != following.get("departure_airport"):
                warnings.append(
                    f"booking {ref}: {previous.get('flight_number')} arrives at "
                    f"{previous.get('arrival_airport')} but "
                    f"{following.get('flight_number')} departs from "
                    f"{following.get('departure_airport')}"
                )
    return warnings


def validate_flights(flights: list[dict], *, source: str = "") -> list[dict]:
    """Drop implausible legs and log why. Returns the legs worth keeping."""
    if not flights:
        return flights

    normalise_itinerary_years(flights)

    kept: list[dict] = []
    for flight in flights:
        reason = _reject_reason(flight)
        if reason:
            logger.warning(
                "Discarding implausible flight %s %s->%s%s: %s",
                flight.get("flight_number", "?"),
                flight.get("departure_airport", "?"),
                flight.get("arrival_airport", "?"),
                f" from {source}" if source else "",
                reason,
            )
            continue
        kept.append(flight)

    for warning in check_route_continuity(kept):
        logger.info("Itinerary continuity check — %s", warning)

    return kept
