"""Domain objects + shared constants for the car-rental feature."""

from dataclasses import dataclass
from datetime import date

# A rental longer than this is almost certainly a mistyped year rather than a
# lease, matching the guard `stays.MAX_NIGHTS` applies for the same reason.
MAX_DAYS = 365


@dataclass
class RentalPlace:
    """One end of a rental — where the car is collected, or handed back.

    Two of these rather than one, because a one-way rental is ordinary: two of
    the three bookings in the measured corpus were one-way. Coordinates are
    optional exactly as they are on a segment's station and a stay's property —
    a counter typed by hand still saves, it simply gets no map pin and no
    timezone conversion.
    """

    name: str
    address: str | None
    lat: float | None
    lon: float | None
    timezone: str | None
    # ISO-3166-1 alpha-2 from the geocoder result that was picked, never
    # inferred from the coordinates (see photon.reverse_country for why).
    country_code: str | None


@dataclass
class CarRental:
    id: str
    trip_id: str
    vendor: str
    pickup: RentalPlace
    pickup_datetime: str
    # Local calendar date at the counter, denormalised at write time — see
    # migration 0032 for why this is not derived from the UTC instant on read.
    pickup_date: str
    dropoff: RentalPlace
    dropoff_datetime: str
    dropoff_date: str
    booking_reference: str | None
    vehicle: str | None
    driver_name: str | None
    notes: str | None
    created_by: int | None
    created_by_username: str | None
    created_at: str
    updated_at: str

    @property
    def days(self) -> int | None:
        """Days the car is held, counted on local calendar dates.

        Rental companies bill by 24-hour period, which is a different number —
        this is the one the day planner bands across, so it matches what the
        traveller sees on the calendar rather than what they are charged for.
        """
        try:
            return (
                date.fromisoformat(self.dropoff_date) - date.fromisoformat(self.pickup_date)
            ).days
        except (TypeError, ValueError):
            return None

    @property
    def is_one_way(self) -> bool:
        """Whether the car is handed back somewhere other than where it was
        collected. Read by the UI, which prints one place for a return rental
        and an arrow for a one-way."""
        return self.pickup.name.strip().casefold() != self.dropoff.name.strip().casefold()
