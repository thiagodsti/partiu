"""Migration 0041: the day cards' checklists become planner items."""

import json

from alembic import command


def _cfg():
    from backend.database import _get_alembic_config

    return _get_alembic_config()


def _seed(conn, trip_id, rows):
    conn.execute(
        "INSERT INTO users (id, username, password_hash, is_admin) VALUES (1, 'u', 'x', 0)"
    )
    conn.execute(
        "INSERT INTO trips (id, name, user_id, created_at, updated_at)"
        " VALUES (?, 'T', 1, '2026-01-01', '2026-01-01')",
        (trip_id,),
    )
    for date, content in rows:
        conn.execute(
            "INSERT INTO trip_day_notes (trip_id, date, content, updated_by) VALUES (?, ?, ?, 1)",
            (trip_id, date, content),
        )


class TestChecklistsBecomePlanItems:
    def test_items_move_and_the_note_keeps_its_text(self, test_db):
        import backend.database as db

        command.downgrade(_cfg(), "0040")
        with db.db_write() as conn:
            _seed(
                conn,
                "t1",
                [
                    (
                        "2027-03-25",
                        json.dumps(
                            {
                                "note": "Levar casaco",
                                "items": [
                                    {"text": "Cidade Proibida", "checked": True},
                                    {"text": "  ", "checked": False},
                                    {"text": "Pato de Pequim", "checked": False},
                                    {"text": "x" * 320, "checked": False},
                                ],
                            }
                        ),
                    ),
                    (
                        "2027-03-26",
                        json.dumps(
                            [
                                {"type": "text", "value": "old"},
                                {
                                    "type": "checklist",
                                    "items": [{"text": "Muralha", "checked": False}],
                                },
                            ]
                        ),
                    ),
                    ("2027-03-27", "plain text note"),
                ],
            )
        command.upgrade(_cfg(), "head")

        with db.db_conn() as conn:
            items = conn.execute(
                "SELECT date, title, status, sort_order, created_by FROM trip_plan_items"
                " WHERE trip_id = 't1' ORDER BY date, sort_order"
            ).fetchall()
            notes = dict(
                conn.execute(
                    "SELECT date, content FROM trip_day_notes WHERE trip_id = 't1'"
                ).fetchall()
            )
        assert [tuple(r) for r in items] == [
            ("2027-03-25", "Cidade Proibida", "done", 0, 1),
            ("2027-03-25", "Pato de Pequim", "todo", 1, 1),
            ("2027-03-25", "x" * 300, "todo", 2, 1),
            ("2027-03-26", "Muralha", "todo", 0, 1),
        ]
        assert json.loads(notes["2027-03-25"]) == {"note": "Levar casaco", "items": []}
        with db.db_conn() as conn:
            long_notes = conn.execute(
                "SELECT notes FROM trip_plan_items WHERE title = ?", ("x" * 300,)
            ).fetchone()[0]
        assert long_notes == "x" * 320
        assert json.loads(notes["2027-03-26"]) == {"note": "old", "items": []}
        assert notes["2027-03-27"] == "plain text note"
