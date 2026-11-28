"""SQL for the trip organizer's three tables.

Trip-access authorization is handled by the service layer; this repository only
reads and writes rows, always scoped by ``trip_id`` so an id from another trip
never matches.
"""

import sqlite3

from ..database import db_conn, db_write
from ..utils import now_iso
from .domain import PlanItem, PlanStop, PlanTask

# Columns a caller may update, per table. Anything else (id, trip_id,
# created_by, created_at) is immutable.
_STOP_COLUMNS = ("name", "lat", "lon", "country_code", "start_date", "end_date", "notes")
_ITEM_COLUMNS = (
    "date",
    "time",
    "title",
    "notes",
    "place_name",
    "lat",
    "lon",
    "status",
    "sort_order",
    "image_url",
    "image_page",
)
_TASK_COLUMNS = ("text", "done", "assignee_user_id", "assignee_guest_id")


def _stop(row: sqlite3.Row) -> PlanStop:
    return PlanStop(
        id=row["id"],
        trip_id=row["trip_id"],
        name=row["name"],
        lat=row["lat"],
        lon=row["lon"],
        country_code=row["country_code"],
        start_date=row["start_date"],
        end_date=row["end_date"],
        notes=row["notes"],
    )


def _item(row: sqlite3.Row) -> PlanItem:
    return PlanItem(
        id=row["id"],
        trip_id=row["trip_id"],
        date=row["date"],
        time=row["time"],
        title=row["title"],
        notes=row["notes"],
        place_name=row["place_name"],
        lat=row["lat"],
        lon=row["lon"],
        status=row["status"],
        sort_order=row["sort_order"],
        image_url=row["image_url"],
        image_page=row["image_page"],
    )


def _task(row: sqlite3.Row) -> PlanTask:
    if row["assignee_user_id"] is not None:
        kind, ident = "user", row["assignee_user_id"]
    elif row["assignee_guest_id"] is not None:
        kind, ident = "guest", row["assignee_guest_id"]
    else:
        kind, ident = None, None
    return PlanTask(
        id=row["id"],
        trip_id=row["trip_id"],
        text=row["text"],
        done=bool(row["done"]),
        assignee_type=kind,
        assignee_id=ident,
        sort_order=row["sort_order"],
    )


class PlannerRepository:
    # --- stops -------------------------------------------------------------
    def list_stops(self, trip_id: str) -> list[PlanStop]:
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trip_plan_stops WHERE trip_id = ? ORDER BY start_date, created_at",
                (trip_id,),
            ).fetchall()
        return [_stop(r) for r in rows]

    def get_stop(self, stop_id: str, trip_id: str) -> PlanStop | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT * FROM trip_plan_stops WHERE id = ? AND trip_id = ?", (stop_id, trip_id)
            ).fetchone()
        return _stop(row) if row else None

    def create_stop(self, stop_id: str, trip_id: str, user_id: int, values: dict) -> None:
        now = now_iso()
        with db_write() as conn:
            conn.execute(
                """INSERT INTO trip_plan_stops (id, trip_id, name, lat, lon, country_code,
                       start_date, end_date, notes, created_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    stop_id,
                    trip_id,
                    values["name"],
                    values.get("lat"),
                    values.get("lon"),
                    values.get("country_code"),
                    values["start_date"],
                    values["end_date"],
                    values.get("notes"),
                    user_id,
                    now,
                    now,
                ),
            )

    def update_stop(self, stop_id: str, trip_id: str, values: dict) -> None:
        self._update("trip_plan_stops", _STOP_COLUMNS, stop_id, trip_id, values)

    def delete_stop(self, stop_id: str, trip_id: str) -> None:
        self._delete("trip_plan_stops", stop_id, trip_id)

    # --- items -------------------------------------------------------------
    def list_items(self, trip_id: str) -> list[PlanItem]:
        with db_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM trip_plan_items WHERE trip_id = ?
                   ORDER BY date IS NULL, date, sort_order, time IS NULL, time, created_at""",
                (trip_id,),
            ).fetchall()
        return [_item(r) for r in rows]

    def get_item(self, item_id: str, trip_id: str) -> PlanItem | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT * FROM trip_plan_items WHERE id = ? AND trip_id = ?", (item_id, trip_id)
            ).fetchone()
        return _item(row) if row else None

    def create_item(self, item_id: str, trip_id: str, user_id: int, values: dict) -> None:
        now = now_iso()
        with db_write() as conn:
            last = conn.execute(
                """SELECT COALESCE(MAX(sort_order), -1) FROM trip_plan_items
                   WHERE trip_id = ? AND date IS ?""",
                (trip_id, values.get("date")),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO trip_plan_items (id, trip_id, date, time, title, notes,
                       place_name, lat, lon, status, sort_order, image_url, image_page,
                       created_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item_id,
                    trip_id,
                    values.get("date"),
                    values.get("time"),
                    values["title"],
                    values.get("notes"),
                    values.get("place_name"),
                    values.get("lat"),
                    values.get("lon"),
                    values["status"],
                    last + 1,
                    values.get("image_url"),
                    values.get("image_page"),
                    user_id,
                    now,
                    now,
                ),
            )

    def update_item(self, item_id: str, trip_id: str, values: dict) -> None:
        self._update("trip_plan_items", _ITEM_COLUMNS, item_id, trip_id, values)

    def delete_item(self, item_id: str, trip_id: str) -> None:
        self._delete("trip_plan_items", item_id, trip_id)

    # --- tasks -------------------------------------------------------------
    def list_tasks(self, trip_id: str) -> list[PlanTask]:
        with db_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trip_plan_tasks WHERE trip_id = ? ORDER BY sort_order, created_at",
                (trip_id,),
            ).fetchall()
        return [_task(r) for r in rows]

    def get_task(self, task_id: str, trip_id: str) -> PlanTask | None:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT * FROM trip_plan_tasks WHERE id = ? AND trip_id = ?", (task_id, trip_id)
            ).fetchone()
        return _task(row) if row else None

    def create_task(self, task_id: str, trip_id: str, user_id: int, values: dict) -> None:
        now = now_iso()
        with db_write() as conn:
            last = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) FROM trip_plan_tasks WHERE trip_id = ?",
                (trip_id,),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO trip_plan_tasks (id, trip_id, text, done, assignee_user_id,
                       assignee_guest_id, sort_order, created_by, created_at, updated_at)
                   VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    trip_id,
                    values["text"],
                    values.get("assignee_user_id"),
                    values.get("assignee_guest_id"),
                    last + 1,
                    user_id,
                    now,
                    now,
                ),
            )

    def update_task(self, task_id: str, trip_id: str, values: dict) -> None:
        self._update("trip_plan_tasks", _TASK_COLUMNS, task_id, trip_id, values)

    def delete_task(self, task_id: str, trip_id: str) -> None:
        self._delete("trip_plan_tasks", task_id, trip_id)

    # --- the trip ------------------------------------------------------------
    def add_destination_if_missing(
        self, trip_id: str, name: str, lat, lon, country_code: str | None
    ) -> bool:
        """Append a city to the trip's destinations unless one of that name is
        already there. Returns whether it was added."""
        with db_write() as conn:
            exists = conn.execute(
                "SELECT 1 FROM trip_destinations WHERE trip_id = ? AND lower(name) = lower(?)",
                (trip_id, name),
            ).fetchone()
            if exists:
                return False
            last = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) FROM trip_destinations WHERE trip_id = ?",
                (trip_id,),
            ).fetchone()[0]
            conn.execute(
                """INSERT INTO trip_destinations (id, trip_id, name, lat, lon, country_code,
                       sort_order, created_at)
                   VALUES (lower(hex(randomblob(16))), ?, ?, ?, ?, ?, ?, ?)""",
                (trip_id, name, lat, lon, country_code, last + 1, now_iso()),
            )
        return True

    # --- shared --------------------------------------------------------------
    @staticmethod
    def _update(table: str, allowed: tuple[str, ...], row_id: str, trip_id: str, values: dict):
        columns = [c for c in allowed if c in values]
        if not columns:
            return
        assignments = ", ".join(f"{c} = ?" for c in columns)
        params = [values[c] for c in columns] + [now_iso(), row_id, trip_id]
        with db_write() as conn:
            conn.execute(
                f"UPDATE {table} SET {assignments}, updated_at = ? WHERE id = ? AND trip_id = ?",
                params,
            )

    @staticmethod
    def _delete(table: str, row_id: str, trip_id: str) -> None:
        with db_write() as conn:
            conn.execute(f"DELETE FROM {table} WHERE id = ? AND trip_id = ?", (row_id, trip_id))
