"""The cover photo's subject: the typed destination first.

Before these columns existed the lookup could only resolve an IATA code, so a
trip that was driven or ridden had no photo at all.
"""

from backend.database import db_write
from backend.trips.dto import PlaceFieldsDTO
from backend.trips.image_service import TripImageService
from backend.trips.service import TripService


def _user(username: str) -> int:
    with db_write() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
            (username, "x", 0, "2026-01-01T00:00:00"),
        )
        return cur.lastrowid


class TestDestinationCity:
    def test_typed_destination_is_used(self, test_db):
        service = TripService()
        trip_id = service.create_trip(
            _user("road"),
            "Road trip",
            [],
            "",
            "",
            "",
            "",
            destinations=[PlaceFieldsDTO(name="São Paulo", lat=None, lon=None, country_code="BR")],
        )

        assert TripImageService()._resolve_destination_city(trip_id) == "São Paulo"

    def test_typed_destination_wins_over_the_airport(self, test_db):
        """Both set: the one a person chose is the one that means something."""
        service = TripService()
        trip_id = service.create_trip(
            _user("both"),
            "Mixed",
            [],
            "",
            "",
            "",
            "CDG",
            destinations=[PlaceFieldsDTO(name="Lyon", lat=None, lon=None, country_code="FR")],
        )

        assert TripImageService()._resolve_destination_city(trip_id) == "Lyon"

    def test_falls_back_to_the_airport_city_when_untyped(self, test_db):
        service = TripService()
        trip_id = service.create_trip(_user("flyer"), "Flown", [], "", "", "", "CDG")

        # No airports row in a bare test DB, so the IATA code is its own answer;
        # what matters is that the airport path still runs when nothing is typed.
        assert TripImageService()._resolve_destination_city(trip_id) == "CDG"

    def test_a_multi_stop_trip_picks_one_of_its_destinations(self, test_db):
        """Random, so asking for a different image can move between the trip's
        cities rather than re-rolling photos of the first one."""
        service = TripService()
        trip_id = service.create_trip(
            _user("multi"),
            "Brasil",
            [],
            "",
            "",
            "",
            "",
            destinations=[
                PlaceFieldsDTO(name="São Paulo", lat=None, lon=None, country_code="BR"),
                PlaceFieldsDTO(name="Rio de Janeiro", lat=None, lon=None, country_code="BR"),
            ],
        )

        seen = {TripImageService()._resolve_destination_city(trip_id) for _ in range(40)}
        assert seen == {"São Paulo", "Rio de Janeiro"}

    def test_no_destination_at_all_resolves_to_nothing(self, test_db):
        service = TripService()
        trip_id = service.create_trip(_user("empty"), "Bare", [], "", "", "", "")

        assert TripImageService()._resolve_destination_city(trip_id) is None
