import sqlite3


def can_access_trip(trip_id: str, user_id: int, conn: sqlite3.Connection) -> bool:
    """Return True if user owns the trip OR has an accepted share."""
    row = conn.execute(
        """SELECT 1 FROM trips WHERE id = ? AND user_id = ?
           UNION
           SELECT 1 FROM trip_shares WHERE trip_id = ? AND user_id = ? AND status = 'accepted'
           LIMIT 1""",
        (trip_id, user_id, trip_id, user_id),
    ).fetchone()
    return row is not None


def is_trip_owner(trip_id: str, user_id: int, conn: sqlite3.Connection) -> bool:
    """Return True only if the user owns the trip (not just a collaborator)."""
    row = conn.execute(
        "SELECT 1 FROM trips WHERE id = ? AND user_id = ?", (trip_id, user_id)
    ).fetchone()
    return row is not None


def can_access_flight(flight_id: str, user_id: int, conn: sqlite3.Connection) -> bool:
    """Return True if user owns the flight OR the flight's trip is shared with them."""
    row = conn.execute(
        """SELECT 1 FROM flights f
           WHERE f.id = ? AND (
               f.user_id = ?
               OR EXISTS (
                   SELECT 1 FROM trip_shares ts
                   WHERE ts.trip_id = f.trip_id AND ts.user_id = ? AND ts.status = 'accepted'
               )
           )
           LIMIT 1""",
        (flight_id, user_id, user_id),
    ).fetchone()
    return row is not None
