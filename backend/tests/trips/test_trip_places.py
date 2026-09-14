"""A trip's origin and destination as places the traveller typed.

`origin_airport` / `destination_airport` are derived — `_recompute_span` rewrites
them from the flights and nulls them when there are none — so they can never hold
a typed value, and a trip that is driven has no airport to name at all. These
columns are the user-owned pair.
"""

from backend.database import db_conn, db_write
from backend.trips.dto import PlaceFieldsDTO
from backend.trips.repository import TripRepository
from backend.trips.service import TripService


def _user(username: str = "driver") -> int:
    with db_write() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
            (username, "x", 0, "2026-01-01T00:00:00"),
        )
        return cur.lastrowid


def _places(trip_id: str) -> dict:
    with db_conn() as conn:
        row = conn.execute(
            """SELECT origin_place, origin_lat, origin_lon, origin_country
               FROM trips WHERE id = ?""",
            (trip_id,),
        ).fetchone()
    return dict(row)


def _destinations(trip_id: str) -> list[dict]:
    return TripRepository().list_destinations([trip_id]).get(trip_id, [])


FLORIPA = PlaceFieldsDTO(name="Florianópolis", lat=-27.5954, lon=-48.548, country_code="BR")
SAO_PAULO = PlaceFieldsDTO(name="São Paulo", lat=-23.5505, lon=-46.6333, country_code="BR")


class TestCreateWithPlaces:
    def test_places_are_stored_on_create(self, test_db):
        service = TripService()
        user_id = _user()
        trip_id = service.create_trip(
            user_id,
            "Ano novo",
            [],
            "2026-12-30",
            "2027-01-02",
            "",
            "",
            places=TripService.place_columns("origin", FLORIPA),
            destinations=[SAO_PAULO],
        )

        stored = _places(trip_id)
        assert stored["origin_place"] == "Florianópolis"
        assert stored["origin_lat"] == -27.5954
        assert [d["name"] for d in _destinations(trip_id)] == ["São Paulo"]
        assert _destinations(trip_id)[0]["country_code"] == "BR"

    def test_a_trip_without_places_stores_nothing(self, test_db):
        service = TripService()
        trip_id = service.create_trip(_user("nobody"), "Plain", [], "", "", "", "")
        assert _places(trip_id)["origin_place"] is None
        assert _destinations(trip_id) == []


class TestPlaceColumns:
    def test_a_hand_typed_place_saves_without_coordinates(self, test_db):
        """The geocoder is optional; the name alone still has to save."""
        columns = TripService.place_columns(
            "origin", PlaceFieldsDTO(name="Ubatuba", lat=None, lon=None, country_code=None)
        )
        assert columns["origin_place"] == "Ubatuba"
        assert columns["origin_lat"] is None
        assert columns["origin_country"] is None

    def test_clearing_the_name_clears_the_whole_set(self, test_db):
        """A stale country or coordinate behind a blank label would be a place
        the trip still counts as visited but no longer names."""
        columns = TripService.place_columns(
            "origin", PlaceFieldsDTO(name="   ", lat=1.0, lon=2.0, country_code="PT")
        )
        assert columns == {
            "origin_place": None,
            "origin_lat": None,
            "origin_lon": None,
            "origin_country": None,
        }


class TestUpdate:
    def test_nested_places_are_flattened_on_update(self, test_db):
        service = TripService()
        user_id = _user("editor")
        trip_id = service.create_trip(user_id, "Road trip", [], "", "", "", "")

        service.update_trip(trip_id, user_id, {"origin": FLORIPA})

        assert _places(trip_id)["origin_place"] == "Florianópolis"
        # The nested key must not have reached the table as a column.
        with db_conn() as conn:
            columns = {r[1] for r in conn.execute("PRAGMA table_info(trips)")}
        assert "origin" not in columns

    def test_recompute_span_does_not_touch_the_typed_ends(self, test_db):
        """The whole point of the separate columns: the flight-derived pair is
        rewritten on every mutation, and these must survive it."""
        service = TripService()
        repo = TripRepository()
        user_id = _user("survivor")
        trip_id = service.create_trip(
            user_id,
            "Rail",
            [],
            "",
            "",
            "GRU",
            "CDG",
            destinations=[SAO_PAULO],
        )

        repo.recompute_span(trip_id, "2026-08-01T00:00:00")

        with db_conn() as conn:
            row = conn.execute(
                "SELECT destination_airport FROM trips WHERE id = ?", (trip_id,)
            ).fetchone()
        assert row["destination_airport"] is None  # derived, and there are no flights
        assert [d["name"] for d in _destinations(trip_id)] == ["São Paulo"]  # typed, untouched


class TestUpdateRouteShape:
    """The two routes hand places over in different shapes.

    Create passes the `PlaceFieldsDTO` through; update goes via
    `body.model_dump()`, which turns nested models into plain dicts. Assuming
    the object form crashed **every** trip edit with a 500 — the edit form
    always sends both places, so it was never only date changes that broke.
    """

    def test_place_columns_accepts_a_plain_dict(self, test_db):
        columns = TripService.place_columns(
            "origin",
            {"name": "Florianópolis", "lat": -27.5954, "lon": -48.548, "country_code": "BR"},
        )
        assert columns == {
            "origin_place": "Florianópolis",
            "origin_lat": -27.5954,
            "origin_lon": -48.548,
            "origin_country": "BR",
        }

    def test_a_dict_with_a_blank_name_clears_the_set(self, test_db):
        columns = TripService.place_columns("origin", {"name": "  ", "country_code": "PT"})
        assert set(columns.values()) == {None}

    def test_editing_a_trip_the_way_the_route_does_it(self, test_db):
        from backend.trips.dto import TripUpdateDTO

        service = TripService()
        user_id = _user("editor-route")
        trip_id = service.create_trip(user_id, "T", [], "2026-09-14", "2026-09-19", "", "")

        body = TripUpdateDTO(
            name="T",
            start_date="2026-09-14",
            end_date="2026-09-18",
            origin=FLORIPA,
            destinations=[SAO_PAULO],
        )
        service.update_trip(trip_id, user_id, body.model_dump(exclude_none=True))

        assert _places(trip_id)["origin_place"] == "Florianópolis"
        assert [d["name"] for d in _destinations(trip_id)] == ["São Paulo"]
