"""Tests for backend.routes.stats — haversine, CO₂, and the /api/stats endpoint."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Unit tests: pure functions
# ---------------------------------------------------------------------------


class TestHaversine:
    def test_same_point_is_zero(self):
        from backend.routes.stats import _haversine

        assert _haversine(0, 0, 0, 0) == 0.0

    def test_known_distance_gru_lhr(self):
        # GRU São Paulo (-23.43, -46.47) → LHR London (51.48, -0.46) ≈ 9 465 km
        from backend.routes.stats import _haversine

        km = _haversine(-23.43, -46.47, 51.48, -0.46)
        assert 9_200 < km < 9_700

    def test_short_hop(self):
        # GRU São Paulo → CGH Congonhas — same city, should be < 30 km
        from backend.routes.stats import _haversine

        km = _haversine(-23.43, -46.47, -23.63, -46.66)
        assert km < 30


class TestCo2Kg:
    def test_short_haul_uses_higher_factor(self):
        from backend.routes.stats import _co2_kg

        # 1 000 km × 0.255 = 255 kg
        result = _co2_kg(1_000)
        assert abs(result - 255.0) < 1

    def test_long_haul_uses_lower_factor(self):
        from backend.routes.stats import _co2_kg

        # 10 000 km × 0.195 = 1 950 kg
        result = _co2_kg(10_000)
        assert abs(result - 1_950.0) < 1

    def test_boundary_3000_km_is_short(self):
        from backend.routes.stats import _co2_kg

        # exactly 3 000 km → short-haul factor
        result = _co2_kg(3_000)
        assert abs(result - 765.0) < 1

    def test_zero_distance(self):
        from backend.routes.stats import _co2_kg

        assert _co2_kg(0) == 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _past_dt(days: int = 10) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT10:00:00")


def _future_dt(days: int = 30) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%dT10:00:00")


def _create_flight(client, dep_dt: str | None = None, arr_dt: str | None = None, **kwargs):
    """Create a flight via the API. Returns flight id."""
    payload = {
        "flight_number": "LA8094",
        "departure_airport": "GRU",
        "departure_datetime": dep_dt or _past_dt(10),
        "arrival_airport": "LHR",
        "arrival_datetime": arr_dt or _past_dt(9),
        **kwargs,
    }
    with patch("backend.aircraft_sync.fetch_aircraft_for_new_flights"):
        r = client.post("/api/flights", json=payload)
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------------------------------------------------------------------------
# Integration tests: /api/stats endpoint
# ---------------------------------------------------------------------------


class TestStatsEmpty:
    def test_empty_returns_zeros(self, auth_client):
        r = auth_client.get("/api/stats")
        assert r.status_code == 200
        data = r.json()
        assert data["total_flights"] == 0
        assert data["total_km"] == 0
        assert data["total_co2_kg"] == 0.0
        assert data["flights_by_period"] == []

    def test_year_filter_empty(self, auth_client):
        r = auth_client.get("/api/stats?year=2020")
        assert r.status_code == 200
        data = r.json()
        assert data["total_flights"] == 0
        # year view always returns 12 monthly buckets even when empty
        assert len(data["flights_by_period"]) == 12
        assert all(p["count"] == 0 for p in data["flights_by_period"])


class TestStatsWithFlights:
    def test_totals_increase_with_flights(self, auth_client):
        _create_flight(auth_client)
        r = auth_client.get("/api/stats")
        assert r.status_code == 200
        data = r.json()
        assert data["total_flights"] == 1

    def test_co2_present_when_airports_have_coords(self, auth_client, test_db):
        # Seed real coordinates so haversine returns a non-zero distance
        from backend.database import db_write

        with db_write() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO airports (iata_code, name, city_name, country_code, latitude, longitude)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("GRU", "Guarulhos Intl", "Sao Paulo", "BR", -23.4356, -46.4731),
            )
            conn.execute(
                "INSERT OR REPLACE INTO airports (iata_code, name, city_name, country_code, latitude, longitude)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("LHR", "London Heathrow", "London", "GB", 51.4775, -0.4614),
            )

        _create_flight(auth_client)
        r = auth_client.get("/api/stats")
        data = r.json()
        # GRU→LHR is ~9 400 km (long haul) → co2 > 1 000 kg
        assert data["total_co2_kg"] > 1_000
        # Each flight breakdown entry also carries co2_kg
        assert data["flight_breakdown"][0]["co2_kg"] > 0

    def test_co2_short_haul_higher_factor(self, auth_client, test_db):
        from backend.database import db_write

        # Seed real coordinates — CGH and GIG are ~360 km apart (short haul)
        with db_write() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO airports (iata_code, name, city_name, country_code, latitude, longitude)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("CGH", "Sao Paulo Congonhas", "Sao Paulo", "BR", -23.6261, -46.6563),
            )
            conn.execute(
                "INSERT OR REPLACE INTO airports (iata_code, name, city_name, country_code, latitude, longitude)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                ("GIG", "Rio Galeao", "Rio de Janeiro", "BR", -22.8099, -43.2506),
            )
        _create_flight(
            auth_client,
            departure_airport="CGH",
            arrival_airport="GIG",
            flight_number="LA3001",
        )
        r = auth_client.get("/api/stats")
        data = r.json()
        # Short haul uses 0.255 factor; ~360 km × 0.255 ≈ 92 kg
        assert 0 < data["total_co2_kg"] < 200

    def test_flights_by_period_year_view_has_12_buckets(self, auth_client):
        year = datetime.now(UTC).year
        _create_flight(auth_client)
        r = auth_client.get(f"/api/stats?year={year}")
        data = r.json()
        assert len(data["flights_by_period"]) == 12
        # Labels should be "YYYY-MM" format
        assert all(len(p["label"]) == 7 for p in data["flights_by_period"])
        # Total count across all months equals number of flights in that year
        assert sum(p["count"] for p in data["flights_by_period"]) == data["total_flights"]

    def test_flights_by_period_all_time_by_year(self, auth_client):
        _create_flight(auth_client)
        r = auth_client.get("/api/stats")
        data = r.json()
        # All-time view: labels are 4-char years
        assert all(len(p["label"]) == 4 for p in data["flights_by_period"])
        assert sum(p["count"] for p in data["flights_by_period"]) == data["total_flights"]

    def test_years_list_populated(self, auth_client):
        _create_flight(auth_client)
        r = auth_client.get("/api/stats")
        data = r.json()
        assert len(data["years"]) >= 1

    def test_top_routes_and_airports(self, auth_client):
        _create_flight(auth_client)
        _create_flight(auth_client, flight_number="LA8095")
        r = auth_client.get("/api/stats")
        data = r.json()
        # GRU→LHR appeared twice
        assert data["top_routes"][0]["key"] == "GRU→LHR"
        assert data["top_routes"][0]["count"] == 2

    def test_upcoming_flights_excluded(self, auth_client):
        # Only past flights (arrival_datetime < now) are counted in stats
        _create_flight(
            auth_client,
            dep_dt=_future_dt(1),
            arr_dt=_future_dt(2),
            flight_number="LA9999",
        )
        r = auth_client.get("/api/stats")
        data = r.json()
        assert data["total_flights"] == 0


# ---------------------------------------------------------------------------
# Integration tests: CSV export
# ---------------------------------------------------------------------------


class TestFlightExport:
    def test_export_csv_empty(self, auth_client):
        r = auth_client.get("/api/flights/export.csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        lines = r.text.strip().split("\n")
        # Only header row when no flights
        assert len(lines) == 1
        assert "Flight" in lines[0]

    def test_export_csv_contains_flight(self, auth_client):
        _create_flight(auth_client, flight_number="LA8094")
        r = auth_client.get("/api/flights/export.csv")
        assert r.status_code == 200
        lines = r.text.strip().split("\n")
        assert len(lines) == 2  # header + 1 flight
        assert "LA8094" in lines[1]

    def test_export_csv_unauthenticated(self, client):
        r = client.get("/api/flights/export.csv")
        assert r.status_code in (401, 403)
