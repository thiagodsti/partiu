"""Repository for the `boarding_passes` table and its on-disk image files.

Trip/flight-access authorization for the simple list/upload flows is a cross-cutting
concern handled by the service layer (see backend.auth). The two composite
lookups below (`get_with_read_access`, `get_owned`) embed their access check because
they need the row's flight_id (or a join) to do the check in the first place —
splitting them into "check, then fetch" would mean two round trips for no benefit.
"""

import uuid
from pathlib import Path

from ..auth import can_access_flight
from ..database import db_conn, db_write
from ..utils import now_iso
from .domain import BoardingPass, TripBoardingPass
from .errors import AccessDeniedError
from .mappers import row_to_boarding_pass, row_to_trip_boarding_pass


class BoardingPassRepository:
    def get_storage_dir(self) -> Path:
        from ..config import settings

        bp_dir = Path(settings.DB_PATH).parent / "boarding_passes"
        bp_dir.mkdir(parents=True, exist_ok=True)
        return bp_dir

    def safe_file_path(self, raw_path: str) -> Path:
        """Resolve a stored path and verify it stays within the storage directory."""
        storage_dir = self.get_storage_dir().resolve()
        resolved = Path(raw_path).resolve()
        if not str(resolved).startswith(str(storage_dir) + "/"):
            raise AccessDeniedError(raw_path)
        return resolved

    def list_for_trip(self, trip_id: str) -> list[TripBoardingPass]:
        with db_conn() as conn:
            rows = conn.execute(
                """SELECT bp.id, bp.flight_id, bp.passenger_name, bp.seat,
                          bp.source_page, bp.created_at,
                          f.flight_number, f.departure_airport, f.arrival_airport
                   FROM boarding_passes bp
                   JOIN flights f ON f.id = bp.flight_id
                   WHERE f.trip_id = ?
                   ORDER BY f.departure_datetime ASC, bp.source_page ASC""",
                (trip_id,),
            ).fetchall()
        return [row_to_trip_boarding_pass(r) for r in rows]

    def list_for_flight(self, flight_id: str) -> list[BoardingPass]:
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM boarding_passes WHERE flight_id = ? ORDER BY source_page ASC, created_at ASC",
                (flight_id,),
            ).fetchall()
        return [row_to_boarding_pass(r) for r in rows]

    def can_read_flight(self, flight_id: str, user_id: int) -> bool:
        with db_conn() as conn:
            return can_access_flight(flight_id, user_id, conn)

    def flight_owned_by(self, flight_id: str, user_id: int) -> bool:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT id FROM flights WHERE id = ? AND user_id = ?", (flight_id, user_id)
            ).fetchone()
        return row is not None

    def get_with_read_access(self, bp_id: str, user_id: int) -> BoardingPass | None:
        """Return the boarding pass if the user has read access (owner or collaborator)."""
        with db_conn() as conn:
            row = conn.execute(
                "SELECT bp.* FROM boarding_passes bp WHERE bp.id = ?", (bp_id,)
            ).fetchone()
            if not row:
                return None
            if not can_access_flight(row["flight_id"], user_id, conn):
                return None
        return row_to_boarding_pass(row)

    def get_owned(self, bp_id: str, user_id: int) -> BoardingPass | None:
        """Return the boarding pass only if the user owns its flight."""
        with db_conn() as conn:
            row = conn.execute(
                """SELECT bp.* FROM boarding_passes bp
                   JOIN flights f ON f.id = bp.flight_id
                   WHERE bp.id = ? AND f.user_id = ?""",
                (bp_id, user_id),
            ).fetchone()
        return row_to_boarding_pass(row) if row else None

    def save(
        self,
        *,
        flight_id: str,
        image_bytes: bytes,
        passenger_name: str | None,
        seat: str | None,
        source_email_id: str | None,
        source_page: int,
    ) -> str:
        """Save a boarding pass image to disk and insert the DB row. Returns the new id."""
        storage_dir = self.get_storage_dir()
        bp_id = str(uuid.uuid4())
        image_path = str(storage_dir / f"{bp_id}.png")
        Path(image_path).write_bytes(image_bytes)

        with db_write() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO boarding_passes
                   (id, flight_id, passenger_name, seat, image_path, source_email_id, source_page, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    bp_id,
                    flight_id,
                    passenger_name or None,
                    seat or None,
                    image_path,
                    source_email_id,
                    source_page,
                    now_iso(),
                ),
            )
        return bp_id

    def delete(self, bp_id: str) -> None:
        with db_write() as conn:
            conn.execute("DELETE FROM boarding_passes WHERE id = ?", (bp_id,))

    def delete_image_file(self, raw_path: str) -> None:
        try:
            self.safe_file_path(raw_path).unlink(missing_ok=True)
        except (OSError, AccessDeniedError):
            pass
