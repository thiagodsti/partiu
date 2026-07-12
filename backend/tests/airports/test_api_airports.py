"""Tests for /api/airports routes."""


class TestAirportLookup:
    def test_get_airport_not_found(self, auth_client):
        r = auth_client.get("/api/airports/ZZZ")
        assert r.status_code == 404

    def test_get_airport_found(self, auth_client):
        from backend.database import db_write

        with db_write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO airports (iata_code, name, city_name, country_code, latitude, longitude) "
                "VALUES ('GRU', 'Guarulhos', 'São Paulo', 'BR', -23.43, -46.47)"
            )
        r = auth_client.get("/api/airports/GRU")
        assert r.status_code == 200
        data = r.json()
        assert data["iata_code"] == "GRU"
        assert data["city_name"] == "São Paulo"

    def test_get_airport_case_insensitive(self, auth_client):
        from backend.database import db_write

        with db_write() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO airports (iata_code, name, city_name, country_code, latitude, longitude) "
                "VALUES ('ARN', 'Arlanda', 'Stockholm', 'SE', 59.65, 17.93)"
            )
        r = auth_client.get("/api/airports/arn")
        assert r.status_code == 200
        assert r.json()["iata_code"] == "ARN"
