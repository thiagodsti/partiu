"""Tests for backend.airports.repository (AirportRepository)."""


def _seed_airport(db_path: str, **overrides) -> None:
    import sqlite3

    fields = {
        "iata_code": "GRU",
        "name": "Guarulhos International Airport",
        "city_name": "Sao Paulo",
        "country_code": "BR",
        "latitude": -23.43,
        "longitude": -46.47,
    }
    fields.update(overrides)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO airports (iata_code, name, city_name, country_code, latitude, longitude) "
        "VALUES (:iata_code, :name, :city_name, :country_code, :latitude, :longitude)",
        fields,
    )
    conn.commit()
    conn.close()


class TestGetByIata:
    def test_returns_none_for_unknown_airport(self, test_db):
        from backend.airports.repository import AirportRepository

        assert AirportRepository().get_by_iata("ZZZ") is None

    def test_returns_airport_details(self, test_db):
        from backend.airports.repository import AirportRepository

        _seed_airport(test_db)

        airport = AirportRepository().get_by_iata("GRU")
        assert airport is not None
        assert airport["city_name"] == "Sao Paulo"
        assert airport["latitude"] == -23.43

    def test_case_insensitive(self, test_db):
        from backend.airports.repository import AirportRepository

        _seed_airport(test_db)

        assert AirportRepository().get_by_iata("gru") is not None


class TestSearch:
    def test_empty_when_no_match(self, test_db):
        from backend.airports.repository import AirportRepository

        assert AirportRepository().search("zzz") == []

    def test_exact_iata_match_ranked_first(self, test_db):
        from backend.airports.repository import AirportRepository

        _seed_airport(test_db, iata_code="ARN", name="Stockholm Arlanda", city_name="Stockholm")
        _seed_airport(test_db, iata_code="ARL", name="Arlington Municipal", city_name="Arlington")

        results = AirportRepository().search("ARN")
        assert results[0]["iata_code"] == "ARN"

    def test_matches_by_city_name(self, test_db):
        from backend.airports.repository import AirportRepository

        _seed_airport(test_db)

        results = AirportRepository().search("Sao Paulo")
        assert any(r["iata_code"] == "GRU" for r in results)

    def test_respects_limit(self, test_db):
        from backend.airports.repository import AirportRepository

        for i in range(5):
            _seed_airport(
                test_db, iata_code=f"A{i:02d}", name=f"Airport {i}", city_name="Testville"
            )

        results = AirportRepository().search("Testville", limit=2)
        assert len(results) == 2


class TestCount:
    def test_zero_by_default(self, test_db):
        from backend.airports.repository import AirportRepository

        assert AirportRepository().count() == 0

    def test_reflects_seeded_rows(self, test_db):
        from backend.airports.repository import AirportRepository

        _seed_airport(test_db)

        assert AirportRepository().count() == 1


class TestLoadFromCsvIfEmpty:
    def test_noop_when_already_populated(self, test_db):
        from pathlib import Path

        from backend.airports.repository import AirportRepository
        from backend.database import get_db_path

        _seed_airport(test_db)
        # A broken CSV at the expected path — if this were read, loading would blow up.
        csv_path = Path(get_db_path()).parent / "airports.csv"
        csv_path.write_text("garbage that would fail to parse")

        # Should return immediately (count already > 0) without touching the CSV.
        AirportRepository().load_from_csv_if_empty()

        assert AirportRepository().count() == 1

    def test_loads_valid_rows_from_csv(self, test_db):
        from pathlib import Path

        from backend.airports.repository import AirportRepository
        from backend.database import get_db_path

        csv_path = Path(get_db_path()).parent / "airports.csv"
        csv_path.write_text(
            "iata_code,icao_code,name,municipality,iso_country,latitude_deg,longitude_deg\n"
            "GRU,SBGR,Guarulhos International Airport,Sao Paulo,BR,-23.43,-46.47\n"
            "LHR,EGLL,London Heathrow Airport,London,GB,51.47,-0.46\n"
        )

        AirportRepository().load_from_csv_if_empty()

        assert AirportRepository().count() == 2
        gru = AirportRepository().get_by_iata("GRU")
        assert gru is not None
        assert gru["city_name"] == "Sao Paulo"

    def test_skips_rows_with_invalid_iata_code(self, test_db):
        from pathlib import Path

        from backend.airports.repository import AirportRepository
        from backend.database import get_db_path

        csv_path = Path(get_db_path()).parent / "airports.csv"
        csv_path.write_text(
            "iata_code,icao_code,name,municipality,iso_country,latitude_deg,longitude_deg\n"
            ",SBGR,No IATA code,Sao Paulo,BR,-23.43,-46.47\n"
            "TOOLONG,EGLL,Bad IATA code,London,GB,51.47,-0.46\n"
            "GRU,SBGR,Guarulhos International Airport,Sao Paulo,BR,-23.43,-46.47\n"
        )

        AirportRepository().load_from_csv_if_empty()

        assert AirportRepository().count() == 1

    def test_no_crash_when_csv_missing_and_download_fails(self, test_db, monkeypatch):
        import urllib.request

        from backend.airports.repository import AirportRepository

        def _raise(*args, **kwargs):
            raise OSError("network unreachable")

        monkeypatch.setattr(urllib.request, "urlretrieve", _raise)

        # Should not raise even though the CSV is missing and the download fails.
        AirportRepository().load_from_csv_if_empty()

        assert AirportRepository().count() == 0
