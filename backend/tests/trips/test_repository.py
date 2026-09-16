class TestPeopleCounts:
    """`get_people_counts` feeds the companion line on the trips list and the
    trip header. The owner is not counted here — the frontend adds them — so the
    number means the same thing whoever is looking at it."""

    def _trip(self, test_db, trip_id: str, user_id: int = 1) -> None:
        from backend.database import db_write

        with db_write() as conn:
            conn.execute(
                "INSERT INTO users (id, username, password_hash, created_at) "
                "VALUES (?, ?, 'x', '2026-01-01') ON CONFLICT(id) DO NOTHING",
                (user_id, f"user{user_id}"),
            )
            conn.execute(
                "INSERT INTO trips (id, name, user_id, created_at, updated_at) "
                "VALUES (?, ?, ?, '2026-01-01', '2026-01-01')",
                (trip_id, f"Trip {trip_id}", user_id),
            )

    def _share(self, test_db, trip_id: str, user_id: int, status: str) -> None:
        from backend.database import db_write

        with db_write() as conn:
            conn.execute(
                "INSERT INTO users (id, username, password_hash, created_at) "
                "VALUES (?, ?, 'x', '2026-01-01') ON CONFLICT(id) DO NOTHING",
                (user_id, f"user{user_id}"),
            )
            conn.execute(
                "INSERT INTO trip_shares (trip_id, user_id, invited_by, status) VALUES (?, ?, 1, ?)",
                (trip_id, user_id, status),
            )

    def test_accepted_and_pending_are_counted_apart(self, test_db):
        from backend.trips.repository import TripRepository

        self._trip(test_db, "t1")
        self._share(test_db, "t1", 2, "accepted")
        self._share(test_db, "t1", 3, "accepted")
        self._share(test_db, "t1", 4, "pending")

        counts = TripRepository().get_people_counts(["t1"])
        assert counts["t1"] == {"accepted": 2, "pending": 1, "guests": 0}

    def test_a_rejected_invitation_counts_as_nothing(self, test_db):
        """Not a collaborator and not an open invitation — it is simply over."""
        from backend.trips.repository import TripRepository

        self._trip(test_db, "t2")
        self._share(test_db, "t2", 2, "rejected")

        assert TripRepository().get_people_counts(["t2"]) == {}

    def test_a_solo_trip_reports_nothing_rather_than_zeroes(self, test_db):
        from backend.trips.repository import TripRepository

        self._trip(test_db, "t3")
        assert TripRepository().get_people_counts(["t3"]) == {}

    def test_no_trip_ids_is_not_a_query(self, test_db):
        from backend.trips.repository import TripRepository

        assert TripRepository().get_people_counts([]) == {}

    def test_counts_are_kept_per_trip(self, test_db):
        from backend.trips.repository import TripRepository

        self._trip(test_db, "t4")
        self._trip(test_db, "t5")
        self._share(test_db, "t4", 2, "accepted")
        self._share(test_db, "t5", 3, "pending")

        counts = TripRepository().get_people_counts(["t4", "t5"])
        assert counts["t4"] == {"accepted": 1, "pending": 0, "guests": 0}
        assert counts["t5"] == {"accepted": 0, "pending": 1, "guests": 0}

    def test_roster_guests_are_counted_as_people(self, test_db):
        """A trip with three guests and no collaborators has people on it — the
        card and the trip header would otherwise call it a solo trip."""
        from backend.database import db_write
        from backend.trips.repository import TripRepository

        self._trip(test_db, "t6")
        with db_write() as conn:
            for name in ("Jimmy", "Lucas", "Vivian"):
                conn.execute(
                    "INSERT INTO guests (owner_id, name, created_at) VALUES (1, ?, '2026-01-01')",
                    (name,),
                )
            conn.execute(
                "INSERT INTO trip_guests (trip_id, guest_id) "
                "SELECT 't6', id FROM guests WHERE owner_id = 1"
            )

        counts = TripRepository().get_people_counts(["t6"])
        assert counts["t6"] == {"accepted": 0, "pending": 0, "guests": 3}
