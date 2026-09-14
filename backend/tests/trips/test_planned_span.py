"""The span a traveller declares vs. the one their legs imply.

`start_date`/`end_date` are derived — recomputed as MIN/MAX over the trip's
contents — which on its own means a hand-made trip's dates collapse to its first
leg's day. Unioning the declared pair in is what keeps the span usable as the
bound on a date picker: the return leg must not fall outside its own trip.
"""

from backend.database import db_conn, db_write
from backend.trips.repository import TripRepository
from backend.trips.service import TripService


def _user(username: str) -> int:
    with db_write() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?,?,?,?)",
            (username, "x", 0, "2026-01-01T00:00:00"),
        )
        return cur.lastrowid


def _span(trip_id: str) -> tuple:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT start_date, end_date, planned_start_date, planned_end_date FROM trips WHERE id = ?",
            (trip_id,),
        ).fetchone()
    return (row["start_date"], row["end_date"], row["planned_start_date"], row["planned_end_date"])


def _leg(trip_id: str, depart: str, arrive: str, seg_id: str = "s1") -> None:
    with db_write() as conn:
        conn.execute(
            """INSERT INTO trip_segments (id, trip_id, type, departure_place, arrival_place,
                   departure_datetime, arrival_datetime, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                seg_id,
                trip_id,
                "car",
                "Florianópolis",
                "São Paulo",
                depart,
                arrive,
                "2026-08-01T00:00:00",
                "2026-08-01T00:00:00",
            ),
        )


class TestDeclaredSpanSurvives:
    def test_first_leg_does_not_collapse_the_declared_span(self, test_db):
        """The bug this pair exists for: adding a drive on the 31st used to
        rewrite a 30 Dec – 2 Jan trip to 31 Dec – 31 Dec, so the return leg
        would already be outside its own trip."""
        service, repo = TripService(), TripRepository()
        trip_id = service.create_trip(
            _user("newyear"), "Ano novo", [], "2026-12-30", "2027-01-02", "", ""
        )
        _leg(trip_id, "2026-12-31T08:00:00", "2026-12-31T20:00:00")

        repo.recompute_span(trip_id, "2026-08-01T00:01:00")

        start, end, planned_start, planned_end = _span(trip_id)
        assert (start, end) == ("2026-12-30", "2027-01-02")
        assert (planned_start, planned_end) == ("2026-12-30", "2027-01-02")

    def test_a_leg_outside_the_declaration_still_extends_the_trip(self, test_db):
        """The union grows; it does not clamp. Plans change."""
        service, repo = TripService(), TripRepository()
        trip_id = service.create_trip(
            _user("extender"), "Road trip", [], "2026-12-30", "2027-01-02", "", ""
        )
        _leg(trip_id, "2027-01-05T08:00:00", "2027-01-05T20:00:00")

        repo.recompute_span(trip_id, "2026-08-01T00:01:00")

        start, end, _, _ = _span(trip_id)
        assert (start, end) == ("2026-12-30", "2027-01-05")

    def test_editing_the_dates_is_how_a_span_shrinks(self, test_db):
        service = TripService()
        user_id = _user("shrinker")
        trip_id = service.create_trip(user_id, "Long", [], "2026-01-01", "2026-12-31", "", "")

        service.update_trip(
            trip_id, user_id, {"start_date": "2026-06-01", "end_date": "2026-06-10"}
        )

        start, end, planned_start, planned_end = _span(trip_id)
        assert (planned_start, planned_end) == ("2026-06-01", "2026-06-10")
        assert (start, end) == ("2026-06-01", "2026-06-10")

    def test_an_auto_generated_trip_declares_nothing(self, test_db):
        """Auto-grouping has no declaration to make — only contents."""
        repo = TripRepository()
        _user("sync")
        repo.create(
            trip_id="auto",
            name="LA800",
            booking_refs_json='["ABC"]',
            start_date="2026-03-01",
            end_date="2026-03-05",
            origin_airport="GRU",
            destination_airport="LIS",
            user_id=1,
            now="2026-02-01T00:00:00",
            is_auto_generated=True,
        )

        _, _, planned_start, planned_end = _span("auto")
        assert planned_start is None and planned_end is None

    def test_a_dateless_trip_declares_nothing(self, test_db):
        """An empty date field must not become an empty *string* in the declared
        pair — `MIN('', '2026-12-31')` is `''`, which would drag the derived span
        back to the beginning of time."""
        service = TripService()
        trip_id = service.create_trip(_user("blank"), "Someday", [], "", "", "", "")

        start, end, planned_start, planned_end = _span(trip_id)
        assert (planned_start, planned_end) == (None, None)
        assert not start and not end

    def test_an_empty_declaration_cannot_drag_the_span_backwards(self, test_db):
        service, repo = TripService(), TripRepository()
        trip_id = service.create_trip(_user("nodates"), "Someday", [], "", "", "", "")
        _leg(trip_id, "2026-12-31T08:00:00", "2026-12-31T20:00:00")

        repo.recompute_span(trip_id, "2026-08-01T00:01:00")

        start, end, _, _ = _span(trip_id)
        assert (start, end) == ("2026-12-31", "2026-12-31")
