"""Use cases for trip stays: trip-access checks, validation, and the local→UTC
conversion that keeps accommodation comparable with flights and ground legs.

Storage matches `segments`: datetimes are stored as UTC alongside the IANA
timezone of the property, so the frontend can render local time there. What is
different, and deliberate, is the pair of denormalised local *dates* written
next to them. A hotel booking's identity is its local calendar dates — "14-18
October" is true regardless of what those instants are in UTC — and SQLite
cannot convert timezones, so deriving the date from the instant on read would
put a 15:00 check-in at UTC-10 on the wrong day in `_recompute_span` and in the
day planner alike.

Validation is intentionally thin. A stay is *not* required to fall inside the
trip's dates: the trip span is derived from its own contents, so the rule would
be circular, and it would reject the airport hotel booked for the night before
an early departure. Stays extend the span instead (see `_recompute_trip_span`),
and the only hard rejections are the ones that are certainly mistakes — a
check-out at or before check-in, and a booking longer than a year. Anything
merely surprising is surfaced as a non-blocking warning in the UI.
"""

import uuid
from datetime import UTC, date, datetime

from ..airports.timezone import get_timezone_for_coords, localize_naive_to_utc
from ..utils import now_iso
from .domain import MAX_NIGHTS, STAY_KINDS, Stay
from .errors import StayNotFoundError, TripAccessError
from .repository import StayRepository

__all__ = ["StayNotFoundError", "StayService", "TripAccessError", "stay_service"]


def _parse_local(value: str, field: str) -> datetime:
    """Parse a client-supplied local datetime.

    Accepts the ``datetime-local`` input format ("2026-10-04T15:00") and full
    ISO 8601, normalising a trailing "Z" — the same leniency segments applies,
    for the same reason: clients send it inconsistently.
    """
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise ValueError(f"{field} is not a valid datetime") from None


def _local_date(instant: datetime, tz_name: str | None) -> str:
    """The calendar date of ``instant`` as read at the property.

    With no timezone the instant was stored as-given (``localize_naive_to_utc``
    falls back to tagging it UTC), so reading it back in UTC returns exactly the
    date the user typed.
    """
    if tz_name:
        try:
            from zoneinfo import ZoneInfo

            return instant.astimezone(ZoneInfo(tz_name)).date().isoformat()
        except Exception:  # noqa: BLE001 - unknown zone degrades to UTC, as elsewhere
            pass
    return instant.astimezone(UTC).date().isoformat()


class StayService:
    def __init__(self, repository: StayRepository | None = None):
        self._repository = repository or StayRepository()

    def list_stays(self, trip_id: str, user_id: int) -> list[Stay]:
        self._check_access(trip_id, user_id)
        return self._repository.list_for_trip(trip_id)

    def create_stay(self, trip_id: str, user_id: int, data: dict) -> str:
        self._check_access(trip_id, user_id)
        values = self._build_values(data)
        stay_id = str(uuid.uuid4())
        self._repository.create(stay_id, trip_id, user_id, values)
        self._recompute_trip_span(trip_id)
        return stay_id

    def update_stay(self, trip_id: str, stay_id: str, user_id: int, data: dict) -> None:
        self._check_access(trip_id, user_id)
        existing = self._repository.get(stay_id, trip_id)
        if existing is None:
            raise StayNotFoundError(stay_id)

        # _build_values always returns a full row, so a partial update has to be
        # merged onto the stored stay first — otherwise a PATCH moving only the
        # check-out would null every untouched field, and would validate the new
        # check-out against nothing instead of against the stored check-in.
        merged: dict = {
            "kind": data.get("kind") or existing.kind,
            "place": data.get("place")
            or {
                "name": existing.place.name,
                "address": existing.place.address,
                "lat": existing.place.lat,
                "lon": existing.place.lon,
                "country_code": existing.place.country_code,
            },
            "check_in_datetime": data.get("check_in_datetime") or existing.check_in_datetime,
            "check_out_datetime": data.get("check_out_datetime") or existing.check_out_datetime,
        }
        for key in ("booking_reference", "confirmation", "contact", "room_type", "guests", "notes"):
            merged[key] = data[key] if key in data else getattr(existing, key)

        values = self._build_values(merged)
        self._repository.update(stay_id, trip_id, values)
        self._recompute_trip_span(trip_id)

    def delete_stay(self, trip_id: str, stay_id: str, user_id: int) -> None:
        self._check_access(trip_id, user_id)
        if self._repository.get(stay_id, trip_id) is None:
            raise StayNotFoundError(stay_id)
        self._repository.delete(stay_id, trip_id)
        self._recompute_trip_span(trip_id)

    def _build_values(self, data: dict) -> dict:
        kind = (data.get("kind") or "").strip().lower()
        if kind not in STAY_KINDS:
            raise ValueError(f"Unsupported stay kind: {data.get('kind')!r}")

        place = data["place"]
        name = (place.get("name") or "").strip()
        if not name:
            raise ValueError("Place name is required")

        lat, lon = place.get("lat"), place.get("lon")
        tz = get_timezone_for_coords(lat, lon)

        check_in = localize_naive_to_utc(
            _parse_local(data["check_in_datetime"], "check_in_datetime"), tz
        )
        check_out = localize_naive_to_utc(
            _parse_local(data["check_out_datetime"], "check_out_datetime"), tz
        )
        if check_out <= check_in:
            raise ValueError("Check-out must be after check-in")

        check_in_date = _local_date(check_in, tz)
        check_out_date = _local_date(check_out, tz)
        # Counted on local dates, matching Stay.nights — a same-day check-in and
        # check-out is zero nights, which is a day-use booking, not an error.
        nights = (date.fromisoformat(check_out_date) - date.fromisoformat(check_in_date)).days
        if nights > MAX_NIGHTS:
            raise ValueError(f"A stay cannot be longer than {MAX_NIGHTS} nights")

        return {
            "kind": kind,
            "name": name,
            "address": _clean(place.get("address")),
            "lat": lat,
            "lon": lon,
            "timezone": tz,
            # Recorded from the geocoder result, never derived from the
            # coordinates — see photon.reverse_country for why.
            "country": ((place.get("country_code") or "").strip().upper() or None),
            "check_in_datetime": check_in.isoformat(),
            "check_in_date": check_in_date,
            "check_out_datetime": check_out.isoformat(),
            "check_out_date": check_out_date,
            "booking_reference": _clean(data.get("booking_reference")),
            "confirmation": _clean(data.get("confirmation")),
            "contact": _clean(data.get("contact")),
            "room_type": _clean(data.get("room_type")),
            "guests": data.get("guests"),
            "notes": _clean(data.get("notes")),
        }

    @staticmethod
    def _recompute_trip_span(trip_id: str) -> None:
        """Widen (or shrink) the trip's date range to cover this stay.

        Stays extend the span rather than being validated against it — a hotel
        booked for the night before the first flight is a real booking, and a
        trip whose accommodation is arranged before its flights has no span to
        be measured against at all.
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


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


stay_service = StayService()
