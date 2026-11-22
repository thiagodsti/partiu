"""Tests for backend.integrations.routes (known flight routes and the reversed-leg fix).

The standing-data tarball is built in memory with a handful of rows in the
published layout; nothing is downloaded.
"""

import io
import tarfile
from datetime import UTC, datetime, timedelta

import pytest

ROUTES_CSV = (
    "﻿Callsign,Code,Number,AirlineCode,AirportCodes\n"
    "AZU4849,AZU,4849,AZU,SBKP-SBFL\n"
    "ITY2058,ITY,2058,ITY,LIRF-LIML\n"
    "FIN813,FIN,813,FIN,EFHK-EBBR\n"
    "DLH400,DLH,400,DLH,EDDF-KJFK\n"
    "NOROUTE1,NOR,1,NOR,\n"
)
AIRLINES_CSV = (
    "﻿Code,Name,ICAO,IATA,PositioningFlightPattern,CharterFlightPattern\n"
    "AD,Azul,AZU,AD,,\n"
    "AZ,ITA Airways,ITY,AZ,,\n"
    "AY,Finnair,FIN,AY,,\n"
    "LH,Lufthansa,DLH,LH,,\n"
    "1B,Abacus,,1B,,\n"
)
AIRPORTS = [
    ("VCP", "SBKP"),
    ("FLN", "SBFL"),
    ("FCO", "LIRF"),
    ("LIN", "LIML"),
    ("HEL", "EFHK"),
    ("BRU", "EBBR"),
    ("ARN", "ESSA"),
    ("FRA", "EDDF"),
    ("JFK", "KJFK"),
]


def _tarball(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


STANDING_DATA = {
    "standing-data-main/routes/schema-01/A/AZU-all.csv": ROUTES_CSV,
    "standing-data-main/airlines/schema-01/airlines.csv": AIRLINES_CSV,
    "standing-data-main/aircraft/schema-01/A/A-all.csv": "Icao24,Registration\nA1,X\n",
}


@pytest.fixture
def routes_db(test_db):
    from backend.database import db_write
    from backend.integrations.routes.data import parse_tarball, replace_tables

    with db_write() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO airports (iata_code, icao_code, name) VALUES (?, ?, ?)",
            [(iata, icao, iata) for iata, icao in AIRPORTS],
        )
    replace_tables(*parse_tarball(_tarball(STANDING_DATA)))
    return test_db


class TestParse:
    def test_reads_routes_and_airlines_only(self):
        from backend.integrations.routes.data import parse_tarball

        routes, airlines = parse_tarball(_tarball(STANDING_DATA))
        assert ("AZU4849", "SBKP-SBFL") in routes
        assert len(routes) == 4  # the row without airports is skipped
        assert ("AD", "AZU") in airlines
        assert all(len(icao) == 3 for _, icao in airlines)  # 1B has no ICAO code


class TestRefresh:
    def test_failed_download_keeps_the_previous_data(self, routes_db):
        from backend.integrations.routes.data import refresh_routes, route_count

        assert route_count() == 4
        assert refresh_routes("http://127.0.0.1:9/unreachable.tar.gz") == 0
        assert route_count() == 4

    def test_download_without_routes_keeps_the_previous_data(self, routes_db, tmp_path):
        from backend.integrations.routes.data import refresh_routes, route_count

        empty = tmp_path / "empty.tar.gz"
        empty.write_bytes(_tarball({"x/README.md": "nothing"}))
        assert refresh_routes(empty.as_uri()) == 0
        assert route_count() == 4

    def test_successful_refresh_replaces_and_stamps(self, test_db, tmp_path):
        from backend.database import get_global_setting
        from backend.integrations.routes.data import UPDATED_AT_KEY, refresh_routes, route_count

        path = tmp_path / "sd.tar.gz"
        path.write_bytes(_tarball(STANDING_DATA))
        assert refresh_routes(path.as_uri()) == 4
        assert route_count() == 4
        assert get_global_setting(UPDATED_AT_KEY)


class TestCheck:
    def test_known_route_in_iata(self, routes_db):
        from backend.integrations.routes.check import known_routes

        assert known_routes("AD4849") == [["VCP", "FLN"]]
        assert known_routes("AZ 2058") == [["FCO", "LIN"]]

    def test_leading_zeros_are_dropped(self, routes_db):
        from backend.integrations.routes.check import known_routes

        assert known_routes("AY0813") == [["HEL", "BRU"]]

    @pytest.mark.parametrize(
        ("fn", "dep", "arr", "reversed_"),
        [
            ("AD4849", "FLN", "VCP", True),  # the Azul inversion
            ("AD4849", "VCP", "FLN", False),  # right way round
            ("AY813", "HEL", "ARN", False),  # number reused for another route
            ("LA3300", "GRU", "FLN", False),  # unknown callsign
            ("XX", "GRU", "FLN", False),  # not a flight number
        ],
    )
    def test_is_reversed(self, routes_db, fn, dep, arr, reversed_):
        from backend.integrations.routes.check import is_reversed

        assert is_reversed(fn, dep, arr) is reversed_

    def test_fix_swaps_airports_terminals_and_gates_not_times(self, routes_db):
        from backend.integrations.routes.check import fix_reversed_route

        when = datetime(2026, 3, 2, 13, 20, tzinfo=UTC)
        fixed = fix_reversed_route(
            {
                "flight_number": "AD4849",
                "departure_airport": "FLN",
                "arrival_airport": "VCP",
                "departure_datetime": when,
                "departure_terminal": "",
                "arrival_terminal": "2",
                "departure_gate": "",
                "arrival_gate": "",
            }
        )
        assert (fixed["departure_airport"], fixed["arrival_airport"]) == ("VCP", "FLN")
        assert (fixed["departure_terminal"], fixed["arrival_terminal"]) == ("2", "")
        assert fixed["departure_datetime"] == when

    def test_no_data_means_no_change(self, test_db):
        from backend.integrations.routes.check import fix_reversed_route

        leg = {"flight_number": "AD4849", "departure_airport": "FLN", "arrival_airport": "VCP"}
        assert fix_reversed_route(leg) == leg


class TestLlmFallbackUsesIt:
    def test_reversed_llm_leg_is_turned_around(self, routes_db):
        import json
        from unittest.mock import patch

        from backend.integrations.llm import parser
        from backend.parsers.email_connector import EmailMessage

        answer = json.dumps(
            {
                "has_flight": True,
                "booking_reference": "TESTR5",
                "flights": [
                    {
                        "flight_number": "AD4849",
                        "dep_airport": "FLN",
                        "arr_airport": "VCP",
                        "dep_datetime": "2026-03-02T13:20:00",
                        "dep_date": "2026-03-02",
                        "airline_code": "AD",
                    }
                ],
            }
        )
        email = EmailMessage(
            message_id="<t@x>",
            sender="no-reply@voeazul.com.br",
            subject="Reserva TESTR5",
            body="Voo 4849 VCP FLN",
            date=datetime(2026, 1, 5, tzinfo=UTC),
        )
        with (
            patch("backend.config.settings.OLLAMA_URL", "http://ollama:11434"),
            patch.object(parser, "_call_ollama", return_value=answer),
        ):
            (flight,) = parser.llm_extract_flights(email)
        assert (flight["departure_airport"], flight["arrival_airport"]) == ("VCP", "FLN")


class TestSchedule:
    def test_never_refreshed_runs_now(self):
        from backend.scheduler import _next_routes_refresh

        assert _next_routes_refresh("") <= datetime.now(UTC) + timedelta(seconds=1)

    def test_recent_refresh_waits_a_week(self):
        from backend.scheduler import _next_routes_refresh

        last = datetime.now(UTC) - timedelta(days=2)
        due = _next_routes_refresh(last.isoformat())
        assert abs((due - (last + timedelta(days=7))).total_seconds()) < 1

    def test_stale_refresh_runs_now(self):
        from backend.scheduler import _next_routes_refresh

        last = datetime.now(UTC) - timedelta(days=30)
        assert _next_routes_refresh(last.isoformat()) <= datetime.now(UTC) + timedelta(seconds=1)
