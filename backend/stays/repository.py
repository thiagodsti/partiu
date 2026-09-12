"""Repository for the `trip_stays` table.

Trip-access authorization is a cross-cutting concern (see backend.auth.can_access_trip)
and is handled by the service layer — this repository only knows how to read/write rows.
"""

from ..database import db_conn, db_write
from ..utils import now_iso
from .domain import Stay
from .mappers import row_to_stay

_STAY_SELECT = """
    SELECT s.id, s.trip_id, s.kind, s.name, s.address, s.lat, s.lon, s.timezone, s.country,
           s.check_in_datetime, s.check_in_date,
           s.check_out_datetime, s.check_out_date,
           s.booking_reference, s.confirmation, s.contact, s.room_type, s.guests,
           s.notes, s.created_by, s.created_at, s.updated_at,
           u.username AS created_by_username
    FROM trip_stays s
    LEFT JOIN users u ON u.id = s.created_by
"""

# Every column a caller is allowed to update, mapped to its SQL column name.
# Anything not in here (id, trip_id, created_by, created_at) is immutable.
_UPDATABLE: dict[str, str] = {
    "kind": "kind",
    "name": "name",
    "address": "address",
    "lat": "lat",
    "lon": "lon",
    "timezone": "timezone",
    "country": "country",
    "check_in_datetime": "check_in_datetime",
    "check_in_date": "check_in_date",
    "check_out_datetime": "check_out_datetime",
    "check_out_date": "check_out_date",
    "booking_reference": "booking_reference",
    "confirmation": "confirmation",
    "contact": "contact",
    "room_type": "room_type",
    "guests": "guests",
    "notes": "notes",
}


class StayRepository:
    def list_for_trip(self, trip_id: str) -> list[Stay]:
        with db_conn() as conn:
            rows = conn.execute(
                _STAY_SELECT + " WHERE s.trip_id = ? ORDER BY s.check_in_date ASC,"
                " s.check_in_datetime ASC",
                (trip_id,),
            ).fetchall()
        return [row_to_stay(r) for r in rows]

    def get(self, stay_id: str, trip_id: str) -> Stay | None:
        with db_conn() as conn:
            row = conn.execute(
                _STAY_SELECT + " WHERE s.id = ? AND s.trip_id = ?",
                (stay_id, trip_id),
            ).fetchone()
        return row_to_stay(row) if row else None

    def create(self, stay_id: str, trip_id: str, created_by: int, values: dict) -> None:
        now = now_iso()
        with db_write() as conn:
            conn.execute(
                """
                INSERT INTO trip_stays (
                    id, trip_id, kind, name, address, lat, lon, timezone, country,
                    check_in_datetime, check_in_date,
                    check_out_datetime, check_out_date,
                    booking_reference, confirmation, contact, room_type, guests,
                    notes, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stay_id,
                    trip_id,
                    values["kind"],
                    values["name"],
                    values.get("address"),
                    values.get("lat"),
                    values.get("lon"),
                    values.get("timezone"),
                    values.get("country"),
                    values["check_in_datetime"],
                    values["check_in_date"],
                    values["check_out_datetime"],
                    values["check_out_date"],
                    values.get("booking_reference"),
                    values.get("confirmation"),
                    values.get("contact"),
                    values.get("room_type"),
                    values.get("guests"),
                    values.get("notes"),
                    created_by,
                    now,
                    now,
                ),
            )

    def update(self, stay_id: str, trip_id: str, values: dict) -> None:
        """Apply a partial update. Keys not in ``_UPDATABLE`` are ignored, so a
        caller cannot rewrite ``trip_id`` or ``created_by`` through this path."""
        assignments = [f"{column} = ?" for key, column in _UPDATABLE.items() if key in values]
        if not assignments:
            return
        params: list[object] = [values[key] for key in _UPDATABLE if key in values]
        assignments.append("updated_at = ?")
        params.extend([now_iso(), stay_id, trip_id])
        with db_write() as conn:
            conn.execute(
                f"UPDATE trip_stays SET {', '.join(assignments)} WHERE id = ? AND trip_id = ?",
                params,
            )

    def delete(self, stay_id: str, trip_id: str) -> None:
        with db_write() as conn:
            conn.execute(
                "DELETE FROM trip_stays WHERE id = ? AND trip_id = ?",
                (stay_id, trip_id),
            )
