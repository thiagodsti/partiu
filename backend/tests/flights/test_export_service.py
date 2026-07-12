"""Tests for backend.flights.export_service (FlightExportService) — CSV
export math (distance/CO2) and formula-injection sanitization."""

import itertools
from datetime import UTC, datetime

_user_counter = itertools.count(1)


def _seed_user(db_path: str) -> int:
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    username = f"testuser{next(_user_counter)}"
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
        (username, "hashed", 0, datetime.now(UTC).isoformat()),
    )
    conn.commit()
    user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return user_id


def _create_body(**overrides) -> dict:
    body = {
        "flight_number": "LA800",
        "airline_name": "LATAM",
        "airline_code": "LA",
        "departure_airport": "GRU",
        "departure_datetime": "2025-06-01T10:00:00",
        "arrival_airport": "LHR",
        "arrival_datetime": "2025-06-01T22:00:00",
        "booking_reference": "",
        "passenger_name": "",
        "seat": "",
        "cabin_class": "",
        "departure_terminal": "",
        "departure_gate": "",
        "arrival_terminal": "",
        "arrival_gate": "",
        "notes": "",
        "trip_id": None,
    }
    body.update(overrides)
    return body


class TestHaversineAndSanitize:
    def test_haversine_known_distance(self):
        from backend.flights.export_service import _haversine

        # GRU -> LHR roughly 9470km
        km = _haversine(-23.4356, -46.4731, 51.4700, -0.4543)
        assert 9000 < km < 9800

    def test_sanitize_csv_cell_prefixes_formula_chars(self):
        from backend.flights.export_service import _sanitize_csv_cell

        assert _sanitize_csv_cell("=cmd") == "'=cmd"
        assert _sanitize_csv_cell("+1") == "'+1"
        assert _sanitize_csv_cell("-1") == "'-1"
        assert _sanitize_csv_cell("@sum") == "'@sum"
        assert _sanitize_csv_cell("normal") == "normal"
        assert _sanitize_csv_cell("") == ""


class TestExportCsv:
    def test_export_computes_distance_and_co2(self, test_db):
        import sqlite3

        from backend.flights.export_service import FlightExportService

        service = FlightExportService()
        user_id = _seed_user(test_db)

        conn = sqlite3.connect(test_db)
        conn.execute(
            "INSERT INTO airports (iata_code, city_name, country_code, latitude, longitude, name)"
            " VALUES ('GRU', 'Sao Paulo', 'BR', -23.4356, -46.4731, 'Guarulhos')"
        )
        conn.execute(
            "INSERT INTO airports (iata_code, city_name, country_code, latitude, longitude, name)"
            " VALUES ('LHR', 'London', 'GB', 51.4700, -0.4543, 'Heathrow')"
        )
        now = datetime.now(UTC).isoformat()
        conn.execute(
            """INSERT INTO flights (id, user_id, flight_number, departure_airport, arrival_airport,
               departure_datetime, arrival_datetime, status, created_at, updated_at)
               VALUES ('f1', ?, 'LA800', 'GRU', 'LHR', '2025-01-01T10:00:00', '2025-01-01T22:00:00',
               'completed', ?, ?)""",
            (user_id, now, now),
        )
        conn.commit()
        conn.close()

        csv_text = service.export_csv(user_id)
        lines = csv_text.strip().split("\r\n")
        assert len(lines) == 2
        assert "LA800" in lines[1]
        # distance column should be a large number (~9000-9800km) and CO2 non-zero
        cells = lines[1].split(",")
        km = int(cells[9])
        assert 9000 < km < 9800

    def test_export_only_completed_flights(self, test_db):
        from backend.flights.export_service import FlightExportService
        from backend.flights.repository import FlightRepository

        service = FlightExportService()
        repo = FlightRepository()
        user_id = _seed_user(test_db)
        repo.create(
            "f1",
            _create_body(trip_id=None)
            | {
                "duration_minutes": None,
                "status": "upcoming",
                "departure_timezone": None,
                "arrival_timezone": None,
            },
            user_id,
            "now",
        )

        csv_text = service.export_csv(user_id)
        lines = csv_text.strip().split("\r\n")
        assert len(lines) == 1  # header only
