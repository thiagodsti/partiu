"""Use cases for car rentals: trip-access checks, validation, and the local→UTC
conversion that keeps a hired car comparable with flights, ground legs and stays.

Storage matches `stays`: datetimes are UTC alongside the IANA timezone of each
counter, plus the denormalised **local calendar date** at each end. A rental
crosses days the way a stay does — the planner bands it — and SQLite cannot
convert timezones, so deriving the date from the instant on read would land a
09:00 pickup at UTC-10 on the wrong day in `_recompute_span`.

Both ends carry their own zone because a one-way rental can cross one: two of
the three bookings in the measured corpus were one-way, Munich→Vienna and
Trapani→Catania.

Validation is thin, and deliberately so — the same reasoning `stays` sets out. A
rental is **not** required to fall inside the trip's dates: the span is derived
from the trip's own contents, so the rule would be circular, and a car collected
the evening before the first drive is an ordinary booking. Rentals *extend* the
span instead. The only hard rejections are certain mistakes: a drop-off at or
before the pickup, and a rental over a year long (a mistyped year).
"""

import uuid
from datetime import UTC, date, datetime

from ..airports.timezone import get_timezone_for_coords, localize_naive_to_utc
from ..utils import now_iso
from .domain import MAX_DAYS, CarRental
from .errors import CarRentalNotFoundError, TripAccessError
from .repository import CarRentalRepository

__all__ = [
    "CarRentalNotFoundError",
    "CarRentalService",
    "TripAccessError",
    "car_rental_service",
]


def _parse_local(value: str, field: str) -> datetime:
    """Parse a client-supplied local datetime.

    Accepts the ``datetime-local`` input format ("2026-10-04T09:30") and full
    ISO 8601, normalising a trailing "Z" — the same leniency `segments` and
    `stays` apply, for the same reason: clients send it inconsistently.
    """
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise ValueError(f"{field} is not a valid datetime") from None


def _local_date(instant: datetime, tz_name: str | None) -> str:
    """The calendar date of ``instant`` as read at that counter.

    With no timezone the instant was stored as given (``localize_naive_to_utc``
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


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class CarRentalService:
    def __init__(self, repository: CarRentalRepository | None = None):
        self._repository = repository or CarRentalRepository()

    def list_rentals(self, trip_id: str, user_id: int) -> list[CarRental]:
        self._check_access(trip_id, user_id)
        return self._repository.list_for_trip(trip_id)

    def create_rental(self, trip_id: str, user_id: int, data: dict) -> str:
        self._check_access(trip_id, user_id)
        values = self._build_values(data)
        rental_id = str(uuid.uuid4())
        self._repository.create(rental_id, trip_id, user_id, values)
        self._recompute_trip_span(trip_id)
        return rental_id

    def update_rental(self, trip_id: str, rental_id: str, user_id: int, data: dict) -> None:
        self._check_access(trip_id, user_id)
        existing = self._repository.get(rental_id, trip_id)
        if existing is None:
            raise CarRentalNotFoundError(rental_id)

        # `_build_values` always returns a full row, so a partial update has to
        # be merged onto the stored rental first — otherwise a PATCH moving only
        # the drop-off would null every untouched field, *and* would validate the
        # new drop-off against nothing instead of against the stored pickup. Same
        # trap, and the same fix, as `SegmentService.update_segment`.
        merged: dict = {
            "vendor": data.get("vendor") or existing.vendor,
            "pickup": data.get("pickup") or _place_as_dict(existing.pickup),
            "dropoff": data.get("dropoff") or _place_as_dict(existing.dropoff),
            "pickup_datetime": data.get("pickup_datetime") or existing.pickup_datetime,
            "dropoff_datetime": data.get("dropoff_datetime") or existing.dropoff_datetime,
        }
        for key in ("booking_reference", "vehicle", "driver_name", "notes"):
            merged[key] = data[key] if key in data else getattr(existing, key)

        values = self._build_values(merged)
        self._repository.update(rental_id, trip_id, values)
        self._recompute_trip_span(trip_id)

    def delete_rental(self, trip_id: str, rental_id: str, user_id: int) -> None:
        self._check_access(trip_id, user_id)
        if self._repository.get(rental_id, trip_id) is None:
            raise CarRentalNotFoundError(rental_id)
        self._repository.delete(rental_id, trip_id)
        self._recompute_trip_span(trip_id)

    def _build_values(self, data: dict) -> dict:
        vendor = (data.get("vendor") or "").strip()
        if not vendor:
            raise ValueError("Vendor is required")

        pickup = self._place_values(data.get("pickup") or {}, "pickup")
        dropoff = self._place_values(data.get("dropoff") or {}, "dropoff")

        pickup_at = localize_naive_to_utc(
            _parse_local(data["pickup_datetime"], "pickup_datetime"), pickup["timezone"]
        )
        dropoff_at = localize_naive_to_utc(
            _parse_local(data["dropoff_datetime"], "dropoff_datetime"), dropoff["timezone"]
        )
        if dropoff_at <= pickup_at:
            raise ValueError("Drop-off must be after pickup")

        pickup_date = _local_date(pickup_at, pickup["timezone"])
        dropoff_date = _local_date(dropoff_at, dropoff["timezone"])
        days = (date.fromisoformat(dropoff_date) - date.fromisoformat(pickup_date)).days
        if days > MAX_DAYS:
            raise ValueError(f"A rental cannot be longer than {MAX_DAYS} days")

        return {
            "vendor": vendor,
            "pickup_place": pickup["name"],
            "pickup_address": pickup["address"],
            "pickup_lat": pickup["lat"],
            "pickup_lon": pickup["lon"],
            "pickup_timezone": pickup["timezone"],
            "pickup_country": pickup["country"],
            "pickup_datetime": pickup_at.isoformat(),
            "pickup_date": pickup_date,
            "dropoff_place": dropoff["name"],
            "dropoff_address": dropoff["address"],
            "dropoff_lat": dropoff["lat"],
            "dropoff_lon": dropoff["lon"],
            "dropoff_timezone": dropoff["timezone"],
            "dropoff_country": dropoff["country"],
            "dropoff_datetime": dropoff_at.isoformat(),
            "dropoff_date": dropoff_date,
            "booking_reference": _clean(data.get("booking_reference")),
            "vehicle": _clean(data.get("vehicle")),
            "driver_name": _clean(data.get("driver_name")),
            "notes": _clean(data.get("notes")),
        }

    @staticmethod
    def _place_values(place: dict, field: str) -> dict:
        name = (place.get("name") or "").strip()
        if not name:
            raise ValueError(f"{field} place name is required")
        lat, lon = place.get("lat"), place.get("lon")
        return {
            "name": name,
            "address": _clean(place.get("address")),
            "lat": lat,
            "lon": lon,
            "timezone": get_timezone_for_coords(lat, lon),
            # Recorded from the geocoder result, never derived from the
            # coordinates — see photon.reverse_country for why.
            "country": ((place.get("country_code") or "").strip().upper() or None),
        }

    @staticmethod
    def _recompute_trip_span(trip_id: str) -> None:
        """Widen (or shrink) the trip's date range to cover this rental.

        A rental extends the span rather than being validated against it, for
        the same reason a stay does: the span is derived from the trip's own
        contents, and a car collected before the first flight is a real booking.
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


def _place_as_dict(place) -> dict:
    return {
        "name": place.name,
        "address": place.address,
        "lat": place.lat,
        "lon": place.lon,
        "country_code": place.country_code,
    }


car_rental_service = CarRentalService()
