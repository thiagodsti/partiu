"""SQL for AI place suggestions: what a request is about, the traveller's past
trips, the per-user preference, and the daily request count.

Read-only over the planner's and trips' own tables — suggestions never write a
plan row; the traveller adds the ones they want through the planner's API.
"""

from ..auth import can_access_trip
from ..database import db_conn, db_write
from ..utils import now_iso

# Item titles sent so the model does not suggest what is already planned.
_MAX_KNOWN_TITLES = 80


class SuggestionsRepository:
    def can_access(self, trip_id: str, user_id: int) -> bool:
        with db_conn() as conn:
            return can_access_trip(trip_id, user_id, conn)

    def trip(self, trip_id: str) -> dict | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT id, name, start_date, end_date FROM trips WHERE id = ?", (trip_id,)
            ).fetchone()
        return dict(row) if row else None

    def stop(self, trip_id: str, stop_id: str) -> dict | None:
        with db_conn() as conn:
            row = conn.execute(
                """SELECT name, lat, lon, country_code, start_date, end_date
                   FROM trip_plan_stops WHERE id = ? AND trip_id = ?""",
                (stop_id, trip_id),
            ).fetchone()
        return dict(row) if row else None

    def stop_on(self, trip_id: str, day: str) -> dict | None:
        """The route city the traveller is in on ``day``.

        A night belongs to the city slept in, so a stop covers ``start <= day <
        end``; on a stop's last day (a travel day) the next stop wins, and the
        last stop of the route keeps its final day.
        """
        with db_conn() as conn:
            row = conn.execute(
                """SELECT name, lat, lon, country_code, start_date, end_date
                   FROM trip_plan_stops
                   WHERE trip_id = ? AND start_date <= ? AND ? <= end_date
                   ORDER BY (? < end_date) DESC, start_date DESC
                   LIMIT 1""",
                (trip_id, day, day, day),
            ).fetchone()
        return dict(row) if row else None

    def stay_on(self, trip_id: str, day: str) -> dict | None:
        """The stay whose nights include ``day`` (check-in <= day < check-out)."""
        with db_conn() as conn:
            row = conn.execute(
                """SELECT name, address, lat, lon, country
                   FROM trip_stays
                   WHERE trip_id = ? AND check_in_date <= ? AND ? < check_out_date
                   ORDER BY check_in_date DESC LIMIT 1""",
                (trip_id, day, day),
            ).fetchone()
        return dict(row) if row else None

    def first_destination(self, trip_id: str) -> dict | None:
        with db_conn() as conn:
            row = conn.execute(
                """SELECT name, lat, lon, country_code FROM trip_destinations
                   WHERE trip_id = ? ORDER BY sort_order LIMIT 1""",
                (trip_id,),
            ).fetchone()
        return dict(row) if row else None

    def known_titles(self, trip_id: str) -> list[str]:
        with db_conn() as conn:
            rows = conn.execute(
                """SELECT title FROM trip_plan_items WHERE trip_id = ?
                   ORDER BY sort_order LIMIT ?""",
                (trip_id, _MAX_KNOWN_TITLES),
            ).fetchall()
        return [r["title"] for r in rows]

    def items_on(self, trip_id: str, day: str) -> list[dict]:
        """The plan's things to do on ``day``, in the order the board shows."""
        with db_conn() as conn:
            rows = conn.execute(
                """SELECT id, title, time, status, notes, place_name, lat, lon
                   FROM trip_plan_items WHERE trip_id = ? AND date = ?
                   ORDER BY sort_order, time IS NULL, time, created_at""",
                (trip_id, day),
            ).fetchall()
        return [dict(r) for r in rows]

    def rated_trips(self, user_id: int, exclude_trip_id: str, today: str, limit: int) -> list[dict]:
        """Finished trips the traveller is on that carry a rating, newest first.

        A trip's rating and note are shared by everyone on it, so these are the
        trip's, read for a traveller who owns it or accepted an invitation.
        """
        with db_conn() as conn:
            rows = conn.execute(
                """SELECT t.id, t.name, t.rating, t.note, t.end_date,
                          (SELECT group_concat(d.name, ', ')
                             FROM (SELECT name FROM trip_destinations
                                   WHERE trip_id = t.id ORDER BY sort_order) d) AS places
                   FROM trips t
                   WHERE t.rating IS NOT NULL
                     AND t.id != ?
                     AND t.end_date IS NOT NULL AND t.end_date < ?
                     AND (t.user_id = ? OR EXISTS (
                          SELECT 1 FROM trip_shares s
                          WHERE s.trip_id = t.id AND s.user_id = ? AND s.status = 'accepted'))
                   ORDER BY t.end_date DESC
                   LIMIT ?""",
                (exclude_trip_id, today, user_id, user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def locale(self, user_id: int) -> str:
        with db_conn() as conn:
            row = conn.execute("SELECT locale FROM users WHERE id = ?", (user_id,)).fetchone()
        return (row["locale"] if row else None) or "en"

    # --- preference --------------------------------------------------------
    def use_history(self, user_id: int) -> bool:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT use_history FROM ai_suggestion_prefs WHERE user_id = ?", (user_id,)
            ).fetchone()
        return bool(row and row["use_history"])

    def set_use_history(self, user_id: int, value: bool) -> None:
        with db_write() as conn:
            conn.execute(
                """INSERT INTO ai_suggestion_prefs (user_id, use_history, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET use_history = excluded.use_history,
                                                      updated_at = excluded.updated_at""",
                (user_id, 1 if value else 0, now_iso()),
            )

    # --- daily count ---------------------------------------------------------
    def used_on(self, user_id: int, day: str) -> int:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT count FROM ai_suggestion_usage WHERE user_id = ? AND day = ?",
                (user_id, day),
            ).fetchone()
        return row["count"] if row else 0

    def take_one(self, user_id: int, day: str, limit: int) -> bool:
        """Count one request against today's limit; False when none are left.

        Check and increment in one write, so two requests at once cannot both
        take the last one.
        """
        with db_write() as conn:
            row = conn.execute(
                "SELECT count FROM ai_suggestion_usage WHERE user_id = ? AND day = ?",
                (user_id, day),
            ).fetchone()
            used = row["count"] if row else 0
            if used >= limit:
                return False
            conn.execute(
                """INSERT INTO ai_suggestion_usage (user_id, day, count) VALUES (?, ?, 1)
                   ON CONFLICT(user_id, day) DO UPDATE SET count = count + 1""",
                (user_id, day),
            )
        return True
