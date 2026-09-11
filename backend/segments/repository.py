"""Repository for the `trip_segments` table.

Trip-access authorization is a cross-cutting concern (see backend.auth.can_access_trip)
and is handled by the service layer — this repository only knows how to read/write rows.
"""

from ..database import db_conn, db_write
from ..utils import now_iso
from .domain import Segment
from .mappers import row_to_segment

_SEGMENT_SELECT = """
    SELECT s.id, s.trip_id, s.type, s.operator, s.number, s.booking_reference,
           s.departure_place, s.departure_lat, s.departure_lon,
           s.departure_datetime, s.departure_timezone,
           s.arrival_place, s.arrival_lat, s.arrival_lon,
           s.arrival_datetime, s.arrival_timezone,
           s.seat, s.notes, s.created_by, s.created_at, s.updated_at,
           u.username AS created_by_username
    FROM trip_segments s
    LEFT JOIN users u ON u.id = s.created_by
"""

# Every column a caller is allowed to update, mapped to its SQL column name.
# Anything not in here (id, trip_id, created_by, created_at) is immutable.
_UPDATABLE: dict[str, str] = {
    "type": "type",
    "operator": "operator",
    "number": "number",
    "booking_reference": "booking_reference",
    "departure_place": "departure_place",
    "departure_lat": "departure_lat",
    "departure_lon": "departure_lon",
    "departure_datetime": "departure_datetime",
    "departure_timezone": "departure_timezone",
    "arrival_place": "arrival_place",
    "arrival_lat": "arrival_lat",
    "arrival_lon": "arrival_lon",
    "arrival_datetime": "arrival_datetime",
    "arrival_timezone": "arrival_timezone",
    "seat": "seat",
    "notes": "notes",
}


class SegmentRepository:
    def list_for_trip(self, trip_id: str) -> list[Segment]:
        with db_conn() as conn:
            rows = conn.execute(
                _SEGMENT_SELECT + " WHERE s.trip_id = ? ORDER BY s.departure_datetime ASC",
                (trip_id,),
            ).fetchall()
        return [row_to_segment(r) for r in rows]

    def get(self, segment_id: str, trip_id: str) -> Segment | None:
        with db_conn() as conn:
            row = conn.execute(
                _SEGMENT_SELECT + " WHERE s.id = ? AND s.trip_id = ?",
                (segment_id, trip_id),
            ).fetchone()
        return row_to_segment(row) if row else None

    def create(self, segment_id: str, trip_id: str, created_by: int, values: dict) -> None:
        now = now_iso()
        with db_write() as conn:
            conn.execute(
                """
                INSERT INTO trip_segments (
                    id, trip_id, type, operator, number, booking_reference,
                    departure_place, departure_lat, departure_lon,
                    departure_datetime, departure_timezone,
                    arrival_place, arrival_lat, arrival_lon,
                    arrival_datetime, arrival_timezone,
                    seat, notes, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    segment_id,
                    trip_id,
                    values["type"],
                    values.get("operator"),
                    values.get("number"),
                    values.get("booking_reference"),
                    values["departure_place"],
                    values.get("departure_lat"),
                    values.get("departure_lon"),
                    values["departure_datetime"],
                    values.get("departure_timezone"),
                    values["arrival_place"],
                    values.get("arrival_lat"),
                    values.get("arrival_lon"),
                    values["arrival_datetime"],
                    values.get("arrival_timezone"),
                    values.get("seat"),
                    values.get("notes"),
                    created_by,
                    now,
                    now,
                ),
            )

    def update(self, segment_id: str, trip_id: str, values: dict) -> None:
        """Apply a partial update. Keys not in ``_UPDATABLE`` are ignored, so a
        caller cannot rewrite ``trip_id`` or ``created_by`` through this path."""
        assignments = [f"{column} = ?" for key, column in _UPDATABLE.items() if key in values]
        if not assignments:
            return
        params: list[object] = [values[key] for key in _UPDATABLE if key in values]
        assignments.append("updated_at = ?")
        params.extend([now_iso(), segment_id, trip_id])
        with db_write() as conn:
            conn.execute(
                f"UPDATE trip_segments SET {', '.join(assignments)} WHERE id = ? AND trip_id = ?",
                params,
            )

    def delete(self, segment_id: str, trip_id: str) -> None:
        with db_write() as conn:
            conn.execute(
                "DELETE FROM trip_segments WHERE id = ? AND trip_id = ?",
                (segment_id, trip_id),
            )
