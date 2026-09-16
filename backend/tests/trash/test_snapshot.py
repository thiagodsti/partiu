"""The schema-driven snapshot: everything hanging off a trip is collected, in an
order that can be re-inserted, and nothing about the account comes with it."""

import uuid
from datetime import UTC, datetime

import pytest


@pytest.mark.usefixtures("test_db")
class TestCollectGraph:
    @staticmethod
    def _build(test_db):
        import backend.database as db_module

        conn = db_module.get_connection(test_db)
        now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO users (id, username, password_hash, is_admin, created_at) VALUES (1,'t','x',0,?)",
            (now,),
        )
        trip_id, flight_id = str(uuid.uuid4()), str(uuid.uuid4())
        conn.execute(
            "INSERT INTO trips (id, user_id, name, is_auto_generated, created_at, updated_at) VALUES (?,1,'T',0,?,?)",
            (trip_id, now, now),
        )
        conn.execute(
            """INSERT INTO flights (id, user_id, trip_id, airline_code, airline_name, flight_number,
                 departure_airport, arrival_airport, departure_datetime, arrival_datetime,
                 status, is_manually_added, created_at, updated_at, email_message_id)
               VALUES (?,1,?,'TP','TAP','TP783','ARN','LIS','2027-03-10T19:05:00+00:00',
                       '2027-03-10T22:35:00+00:00','upcoming',0,?,?,'<m1@example.com>:TP783')""",
            (flight_id, trip_id, now, now),
        )
        conn.execute(
            "INSERT INTO trip_day_notes (trip_id, date, content, updated_at) VALUES (?, '2027-03-10', 'arrive', ?)",
            (trip_id, now),
        )
        expense_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO trip_expenses (id, trip_id, description, amount, currency, created_by, created_at, updated_at) "
            "VALUES (?, ?, 'taxi', 10, 'EUR', 1, ?, ?)",
            (expense_id, trip_id, now, now),
        )
        conn.execute(
            "INSERT INTO trip_expense_participants (expense_id, user_id) VALUES (?, 1)",
            (expense_id,),
        )
        conn.commit()
        return conn, trip_id, flight_id

    def test_collects_children_and_grandchildren_parents_first(self, test_db):
        from backend.trash.snapshot import collect_graph

        conn, trip_id, flight_id = self._build(test_db)
        graph = collect_graph(conn, "trips", trip_id)
        tables = list(graph)
        assert tables[0] == "trips"
        assert {"flights", "trip_day_notes", "trip_expenses", "trip_expense_participants"} <= set(
            tables
        )
        assert tables.index("trip_expenses") < tables.index("trip_expense_participants")
        assert graph["flights"][0]["id"] == flight_id
        assert "users" not in graph
        conn.close()

    def test_round_trip_restores_every_row(self, test_db):
        from backend.trash.snapshot import collect_graph, restore_graph

        conn, trip_id, _ = self._build(test_db)
        graph = collect_graph(conn, "trips", trip_id)
        conn.execute("DELETE FROM flights WHERE trip_id = ?", (trip_id,))
        conn.execute("DELETE FROM trips WHERE id = ?", (trip_id,))
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM trip_expense_participants").fetchone()[0] == 0

        outcome = restore_graph(conn, graph)
        conn.commit()
        assert outcome["trips"]["restored"] == 1
        assert outcome["trip_expense_participants"]["restored"] == 1
        assert (
            conn.execute("SELECT COUNT(*) FROM flights WHERE trip_id = ?", (trip_id,)).fetchone()[0]
            == 1
        )
        conn.close()

    def test_a_row_that_exists_again_is_skipped_not_clobbered(self, test_db):
        from backend.trash.snapshot import collect_graph, restore_graph

        conn, trip_id, flight_id = self._build(test_db)
        graph = collect_graph(conn, "trips", trip_id)
        conn.execute("UPDATE flights SET seat = '1A' WHERE id = ?", (flight_id,))
        conn.commit()
        outcome = restore_graph(conn, graph)
        conn.commit()
        assert outcome["flights"]["skipped"] == 1
        assert (
            conn.execute("SELECT seat FROM flights WHERE id = ?", (flight_id,)).fetchone()[0]
            == "1A"
        )
        conn.close()

    def test_a_column_the_schema_no_longer_has_is_dropped_on_restore(self, test_db):
        from backend.trash.snapshot import restore_graph

        conn, trip_id, _ = self._build(test_db)
        conn.execute("DELETE FROM trips WHERE id = ?", (trip_id,))
        conn.commit()
        now = datetime.now(UTC).isoformat()
        graph = {
            "trips": [
                {
                    "id": trip_id,
                    "user_id": 1,
                    "name": "T",
                    "is_auto_generated": 0,
                    "created_at": now,
                    "updated_at": now,
                    "gone_column": "x",
                }
            ]
        }
        assert restore_graph(conn, graph)["trips"]["restored"] == 1
        conn.close()
