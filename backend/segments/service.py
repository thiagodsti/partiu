"""Use cases for trip segments: trip-access checks, validation, and the
local→UTC time conversion that keeps segments comparable with flights.

Storage convention matches `flights`: datetimes are stored as UTC, alongside the
IANA timezone name of each end, so the frontend can render local time at the
station. What differs is where the timezone comes from — flights resolve it from
an airport IATA code, segments from the coordinates the station picker attached.
A hand-typed place with no coordinates has no resolvable zone, so its time is
stored as given; that is the same degradation `localize_to_utc` already applies
for an unknown airport.
"""

import uuid
from datetime import datetime

from ..airports.timezone import get_timezone_for_coords, localize_naive_to_utc
from ..utils import now_iso
from .domain import SEGMENT_TYPES, Segment
from .errors import SegmentNotFoundError, TripAccessError
from .repository import SegmentRepository

__all__ = ["SegmentNotFoundError", "SegmentService", "TripAccessError", "segment_service"]


def _parse_local(value: str, field: str) -> datetime:
    """Parse a client-supplied local datetime.

    Accepts the ``datetime-local`` input format ("2026-10-04T08:00") and full
    ISO 8601. A trailing "Z" is normalised because ``fromisoformat`` rejects it
    on older Python versions and clients send it inconsistently.
    """
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise ValueError(f"{field} is not a valid datetime") from None


class SegmentService:
    def __init__(self, repository: SegmentRepository | None = None):
        self._repository = repository or SegmentRepository()

    def list_segments(self, trip_id: str, user_id: int) -> list[Segment]:
        self._check_access(trip_id, user_id)
        return self._repository.list_for_trip(trip_id)

    def create_segment(self, trip_id: str, user_id: int, data: dict) -> str:
        self._check_access(trip_id, user_id)
        values = self._build_values(data)
        segment_id = str(uuid.uuid4())
        self._repository.create(segment_id, trip_id, user_id, values)
        self._recompute_trip_span(trip_id)
        return segment_id

    def update_segment(self, trip_id: str, segment_id: str, user_id: int, data: dict) -> None:
        self._check_access(trip_id, user_id)
        existing = self._repository.get(segment_id, trip_id)
        if existing is None:
            raise SegmentNotFoundError(segment_id)

        # _build_values always returns a full row, so a partial update has to be
        # merged onto the stored segment first. Two reasons, both load-bearing:
        # one end must be re-validated against the other as currently stored (a
        # PATCH moving only the arrival time could otherwise leave the segment
        # arriving before it departs), and any optional field absent from the
        # request must keep its stored value rather than being nulled out.
        merged: dict = {
            "type": data.get("type") or existing.type,
            "departure": data.get("departure")
            or {
                "name": existing.departure.name,
                "lat": existing.departure.lat,
                "lon": existing.departure.lon,
                "country_code": existing.departure.country_code,
            },
            "arrival": data.get("arrival")
            or {
                "name": existing.arrival.name,
                "lat": existing.arrival.lat,
                "lon": existing.arrival.lon,
                "country_code": existing.arrival.country_code,
            },
            "departure_datetime": data.get("departure_datetime") or existing.departure_datetime,
            "arrival_datetime": data.get("arrival_datetime") or existing.arrival_datetime,
        }
        for key in ("operator", "number", "booking_reference", "seat", "notes"):
            merged[key] = data[key] if key in data else getattr(existing, key)

        values = self._build_values(merged)
        self._repository.update(segment_id, trip_id, values)
        self._recompute_trip_span(trip_id)

    def delete_segment(self, trip_id: str, segment_id: str, user_id: int) -> None:
        self._check_access(trip_id, user_id)
        if self._repository.get(segment_id, trip_id) is None:
            raise SegmentNotFoundError(segment_id)
        self._repository.delete(segment_id, trip_id)
        self._recompute_trip_span(trip_id)

    def _build_values(self, data: dict) -> dict:
        segment_type = (data.get("type") or "").strip().lower()
        if segment_type not in SEGMENT_TYPES:
            raise ValueError(f"Unsupported segment type: {data.get('type')!r}")

        departure = data["departure"]
        arrival = data["arrival"]
        dep_name = (departure.get("name") or "").strip()
        arr_name = (arrival.get("name") or "").strip()
        if not dep_name or not arr_name:
            raise ValueError("Departure and arrival places are required")

        dep_lat, dep_lon = departure.get("lat"), departure.get("lon")
        arr_lat, arr_lon = arrival.get("lat"), arrival.get("lon")
        dep_tz = get_timezone_for_coords(dep_lat, dep_lon)
        arr_tz = get_timezone_for_coords(arr_lat, arr_lon)

        dep_utc = localize_naive_to_utc(
            _parse_local(data["departure_datetime"], "departure_datetime"), dep_tz
        )
        arr_utc = localize_naive_to_utc(
            _parse_local(data["arrival_datetime"], "arrival_datetime"), arr_tz
        )
        if arr_utc < dep_utc:
            raise ValueError("Arrival must not be before departure")

        return {
            "type": segment_type,
            "operator": _clean(data.get("operator")),
            "number": _clean(data.get("number")),
            "booking_reference": _clean(data.get("booking_reference")),
            "departure_place": dep_name,
            "departure_lat": dep_lat,
            "departure_lon": dep_lon,
            "departure_datetime": dep_utc.isoformat(),
            "departure_timezone": dep_tz,
            "departure_country": _country(departure),
            "arrival_place": arr_name,
            "arrival_lat": arr_lat,
            "arrival_lon": arr_lon,
            "arrival_datetime": arr_utc.isoformat(),
            "arrival_timezone": arr_tz,
            "arrival_country": _country(arrival),
            "seat": _clean(data.get("seat")),
            "notes": _clean(data.get("notes")),
        }

    @staticmethod
    def _recompute_trip_span(trip_id: str) -> None:
        """Widen (or shrink) the trip's date range to cover this segment.

        Without it the day planner renders no card for a day that holds only a
        train, because its day range comes from the trip's start/end dates —
        which, before segments existed, were derived from flights alone.
        """
        from ..trips.repository import TripRepository

        TripRepository().recompute_span(trip_id, now_iso())

    def _check_access(self, trip_id: str, user_id: int) -> None:
        from ..auth import can_access_trip
        from ..database import db_conn

        with db_conn() as conn:
            allowed = can_access_trip(trip_id, user_id, conn)
        if not allowed:
            raise TripAccessError(trip_id)


def _country(place: dict) -> str | None:
    """The ISO country code the geocoder reported for the picked result.

    Only ever read from the payload — never derived from the coordinates. See
    `photon.reverse_country` for the measurement behind that rule.
    """
    code = (place.get("country_code") or "").strip().upper()
    return code or None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


segment_service = SegmentService()
