"""Cross-cutting trip/flight authorization helpers.

Used throughout the backend (trips, flights, packing, expenses, boarding passes,
day notes, trip documents) — imported as ``from ..auth import can_access_trip`` etc.
Kept dependency-free (just sqlite3) since almost every feature's service layer calls
these with its own short-lived connection.
"""

import sqlite3

from fastapi import HTTPException


def refuse_on_demo(action: str) -> None:
    """Refuse an action that a shared demo account must not allow.

    These are the one-way doors: turning 2FA on puts a code only one visitor's
    phone can produce in front of every later sign-in; changing the password
    invalidates the one printed on the login page; deleting or re-crediting
    accounts does both at once. Recovery from any of them means shell access to
    the server, so a demo refuses them outright rather than trusting that
    nobody will try. Enforced here, in the backend, because the hidden frontend
    control is a courtesy and `curl` does not read it.

    Disabling 2FA is deliberately NOT refused: it is the escape hatch, and on
    an account whose password is published it gives an attacker nothing.
    """
    from ..config import settings

    if settings.DEMO_MODE:
        raise HTTPException(status_code=403, detail=f"{action} is disabled on this demo instance")


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
