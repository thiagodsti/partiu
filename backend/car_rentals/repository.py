"""Repository for the `trip_car_rentals` table.

Trip-access authorization is a cross-cutting concern (see backend.auth.can_access_trip)
and is handled by the service layer — this repository only knows how to read/write rows.
"""

from ..database import db_conn, db_write
from ..utils import now_iso
from .domain import CarRental
from .mappers import row_to_car_rental

_RENTAL_SELECT = """
    SELECT r.id, r.trip_id, r.vendor,
           r.pickup_place, r.pickup_address, r.pickup_lat, r.pickup_lon,
           r.pickup_timezone, r.pickup_country, r.pickup_datetime, r.pickup_date,
           r.dropoff_place, r.dropoff_address, r.dropoff_lat, r.dropoff_lon,
           r.dropoff_timezone, r.dropoff_country, r.dropoff_datetime, r.dropoff_date,
           r.booking_reference, r.vehicle, r.driver_name, r.notes,
           r.created_by, r.created_at, r.updated_at,
           u.username AS created_by_username
    FROM trip_car_rentals r
    LEFT JOIN users u ON u.id = r.created_by
"""

# Every column a caller is allowed to update. Anything not in here (id, trip_id,
# created_by, created_at) is immutable through this path.
_UPDATABLE: tuple[str, ...] = (
    "vendor",
    "pickup_place",
    "pickup_address",
    "pickup_lat",
    "pickup_lon",
    "pickup_timezone",
    "pickup_country",
    "pickup_datetime",
    "pickup_date",
    "dropoff_place",
    "dropoff_address",
    "dropoff_lat",
    "dropoff_lon",
    "dropoff_timezone",
    "dropoff_country",
    "dropoff_datetime",
    "dropoff_date",
    "booking_reference",
    "vehicle",
    "driver_name",
    "notes",
)


class CarRentalRepository:
    def list_for_trip(self, trip_id: str) -> list[CarRental]:
        with db_conn() as conn:
            rows = conn.execute(
                _RENTAL_SELECT + " WHERE r.trip_id = ? ORDER BY r.pickup_date ASC,"
                " r.pickup_datetime ASC",
                (trip_id,),
            ).fetchall()
        return [row_to_car_rental(r) for r in rows]

    def get(self, rental_id: str, trip_id: str) -> CarRental | None:
        with db_conn() as conn:
            row = conn.execute(
                _RENTAL_SELECT + " WHERE r.id = ? AND r.trip_id = ?",
                (rental_id, trip_id),
            ).fetchone()
        return row_to_car_rental(row) if row else None

    def create(self, rental_id: str, trip_id: str, created_by: int | None, values: dict) -> None:
        now = now_iso()
        columns = ("id", "trip_id", *_UPDATABLE, "created_by", "created_at", "updated_at")
        params = (
            rental_id,
            trip_id,
            *(values.get(c) for c in _UPDATABLE),
            created_by,
            now,
            now,
        )
        placeholders = ", ".join("?" * len(columns))
        with db_write() as conn:
            conn.execute(
                f"INSERT INTO trip_car_rentals ({', '.join(columns)}) VALUES ({placeholders})",
                params,
            )

    def update(self, rental_id: str, trip_id: str, values: dict) -> None:
        """Apply an update. Keys outside ``_UPDATABLE`` are ignored, so a caller
        cannot rewrite ``trip_id`` or ``created_by`` through this path."""
        columns = [c for c in _UPDATABLE if c in values]
        if not columns:
            return
        assignments = [f"{c} = ?" for c in columns]
        params: list[object] = [values[c] for c in columns]
        assignments.append("updated_at = ?")
        params.extend([now_iso(), rental_id, trip_id])
        with db_write() as conn:
            conn.execute(
                f"UPDATE trip_car_rentals SET {', '.join(assignments)} "
                "WHERE id = ? AND trip_id = ?",
                params,
            )

    def delete(self, rental_id: str, trip_id: str) -> None:
        with db_write() as conn:
            conn.execute(
                "DELETE FROM trip_car_rentals WHERE id = ? AND trip_id = ?",
                (rental_id, trip_id),
            )

    def count_by_trip(self, trip_ids: list[str]) -> dict[str, int]:
        """Rentals per trip, in one query — the bulk sibling of
        `TripRepository.get_flight_counts` / `get_stay_counts`, used to fill in
        the trips list without a query per card."""
        if not trip_ids:
            return {}
        placeholders = ", ".join("?" * len(trip_ids))
        with db_conn() as conn:
            rows = conn.execute(
                f"""SELECT trip_id, COUNT(*) AS n FROM trip_car_rentals
                    WHERE trip_id IN ({placeholders}) GROUP BY trip_id""",
                trip_ids,
            ).fetchall()
        return {r["trip_id"]: r["n"] for r in rows}
