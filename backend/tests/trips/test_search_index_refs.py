"""A booking reference is typed on the leg now, not on the trip — so the trip
search index has to pick it up from the flights and the ground legs."""

from backend.database import db_write
from backend.trips.repository import TripRepository


def _user(username: str = "searcher") -> int:
    with db_write() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
            (username, "x", 0, "2026-01-01T00:00:00"),
        )
        return cur.lastrowid


def _trip(repo: TripRepository, trip_id: str, user_id: int) -> None:
    repo.create(
        trip_id=trip_id,
        name="Nordics",
        booking_refs_json="[]",
        start_date="2026-09-01",
        end_date="2026-09-05",
        origin_airport="",
        destination_airport="",
        user_id=user_id,
        now="2026-08-01T00:00:00",
    )


class TestSearchIndexBookingRefs:
    def test_flight_reference_is_indexed(self, test_db):
        repo = TripRepository()
        user_id = _user()
        _trip(repo, "t-flight", user_id)
        with db_write() as conn:
            conn.execute(
                """INSERT INTO flights (id, trip_id, user_id, flight_number, departure_airport,
                       arrival_airport, departure_datetime, arrival_datetime, booking_reference,
                       created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "f1",
                    "t-flight",
                    user_id,
                    "LA800",
                    "GRU",
                    "LIS",
                    "2026-09-01T10:00:00",
                    "2026-09-01T23:00:00",
                    "PNR123",
                    "2026-08-01T00:00:00",
                    "2026-08-01T00:00:00",
                ),
            )

        rows = repo.get_search_index_rows(["t-flight"])
        assert "PNR123" in (rows["t-flight"]["booking_refs"] or "")

    def test_segment_reference_is_indexed(self, test_db):
        repo = TripRepository()
        user_id = _user("railfan")
        _trip(repo, "t-rail", user_id)
        with db_write() as conn:
            conn.execute(
                """INSERT INTO trip_segments (id, trip_id, type, departure_place, arrival_place,
                       departure_datetime, arrival_datetime, booking_reference, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "s1",
                    "t-rail",
                    "train",
                    "Stockholm C",
                    "Oslo S",
                    "2026-09-02T07:22:00",
                    "2026-09-02T13:35:00",
                    "SJ-9XK2",
                    "2026-08-01T00:00:00",
                    "2026-08-01T00:00:00",
                ),
            )

        refs = repo.get_segment_booking_refs(["t-rail"])
        assert refs["t-rail"] == "SJ-9XK2"

    def test_a_rail_only_trip_has_no_flight_row_at_all(self, test_db):
        """Why segment refs need their own query: the flight index is
        ``FROM flights``, so a trip with no flights produces no row there."""
        repo = TripRepository()
        user_id = _user("norail")
        _trip(repo, "t-empty", user_id)

        assert repo.get_search_index_rows(["t-empty"]) == {}
        assert repo.get_segment_booking_refs(["t-empty"]) == {}

    def test_empty_input_does_not_query(self, test_db):
        assert TripRepository().get_segment_booking_refs([]) == {}
