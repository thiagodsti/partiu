"""Tests for backend.airports.repository (AirportRepository)."""


def _raise_network_error(*args, **kwargs):
    """Stand-in for urlretrieve on an instance with no outbound network."""
    raise OSError("network unreachable")


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


class TestRankingColumns:
    """The `type` / `scheduled_service` / folded columns that make name
    resolution safe — see backend/parsers/shared.py:resolve_iata."""

    def _write_csv(self, extra_cols: bool = True) -> None:
        from pathlib import Path

        from backend.database import get_db_path

        csv_path = Path(get_db_path()).parent / "airports.csv"
        csv_path.write_text(
            "iata_code,icao_code,type,name,municipality,iso_country,latitude_deg,"
            "longitude_deg,scheduled_service,keywords\n"
            "GRU,SBGR,large_airport,São Paulo/Guarulhos Airport,São Paulo,BR,"
            "-23.43,-46.47,yes,Cumbica\n"
            "SMP,,small_airport,Stockholm Landing Strip,Stockholm,PG,"
            "-5.0,145.0,no,\n"
        )

    def test_csv_load_stores_type_and_service(self, test_db):
        from backend.airports.repository import AirportRepository
        from backend.database import db_conn

        self._write_csv()
        AirportRepository().load_from_csv_if_empty()

        with db_conn() as conn:
            row = conn.execute(
                "SELECT type, scheduled_service FROM airports WHERE iata_code = 'GRU'"
            ).fetchone()
        assert row["type"] == "large_airport"
        assert row["scheduled_service"] == 1

    def test_csv_load_marks_unscheduled_airports(self, test_db):
        from backend.airports.repository import AirportRepository
        from backend.database import db_conn

        self._write_csv()
        AirportRepository().load_from_csv_if_empty()

        with db_conn() as conn:
            row = conn.execute(
                "SELECT scheduled_service FROM airports WHERE iata_code = 'SMP'"
            ).fetchone()
        assert row["scheduled_service"] == 0

    def test_csv_load_stores_accent_folded_columns(self, test_db):
        from backend.airports.repository import AirportRepository
        from backend.database import db_conn

        self._write_csv()
        AirportRepository().load_from_csv_if_empty()

        with db_conn() as conn:
            row = conn.execute(
                "SELECT name_folded, city_folded FROM airports WHERE iata_code = 'GRU'"
            ).fetchone()
        assert row["city_folded"] == "sao paulo"
        assert row["name_folded"] == "sao paulo/guarulhos airport"

    def test_backfill_populates_rows_seeded_without_them(self, test_db):
        from backend.airports.repository import AirportRepository
        from backend.database import db_conn

        _seed_airport(test_db)  # inserted without type/folded columns
        self._write_csv()

        assert AirportRepository().backfill_rank_columns() > 0

        with db_conn() as conn:
            row = conn.execute(
                "SELECT type, scheduled_service, city_folded FROM airports WHERE iata_code = 'GRU'"
            ).fetchone()
        assert row["type"] == "large_airport"
        assert row["scheduled_service"] == 1
        assert row["city_folded"] == "sao paulo"

    def test_backfill_is_a_noop_once_populated(self, test_db):
        from backend.airports.repository import AirportRepository

        self._write_csv()
        AirportRepository().load_from_csv_if_empty()

        assert AirportRepository().backfill_rank_columns() == 0

    def test_backfill_folds_from_stored_rows_when_offline(self, test_db, monkeypatch):
        """No CSV and no network: fold what is stored so search still works."""
        import urllib.request

        from backend.airports.repository import AirportRepository
        from backend.database import db_conn

        monkeypatch.setattr(urllib.request, "urlretrieve", _raise_network_error, raising=True)
        _seed_airport(test_db, iata_code="DUS", name="Düsseldorf Airport", city_name="Düsseldorf")

        AirportRepository().backfill_rank_columns()

        with db_conn() as conn:
            row = conn.execute(
                "SELECT city_folded, type FROM airports WHERE iata_code = 'DUS'"
            ).fetchone()
        assert row["city_folded"] == "dusseldorf"
        assert row["type"] is None  # no ranking data available offline

    def test_backfill_downloads_the_csv_when_missing(self, test_db, monkeypatch):
        """A deployed instance usually has a populated table but no CSV, because
        the data directory is a volume rather than part of the image."""
        import urllib.request
        from pathlib import Path

        from backend.airports.repository import AirportRepository
        from backend.database import db_conn, get_db_path

        _seed_airport(test_db)
        calls: list[str] = []

        def fake_download(url, dest):
            calls.append(url)
            Path(dest).write_text(
                "iata_code,icao_code,type,name,municipality,iso_country,latitude_deg,"
                "longitude_deg,scheduled_service,keywords\n"
                "GRU,SBGR,large_airport,Guarulhos International Airport,Sao Paulo,BR,"
                "-23.43,-46.47,yes,Cumbica\n"
            )

        monkeypatch.setattr(urllib.request, "urlretrieve", fake_download)
        assert not (Path(get_db_path()).parent / "airports.csv").exists()

        AirportRepository().backfill_rank_columns()

        assert len(calls) == 1
        with db_conn() as conn:
            row = conn.execute("SELECT type FROM airports WHERE iata_code = 'GRU'").fetchone()
        assert row["type"] == "large_airport"

    def test_offline_backfill_retries_on_the_next_start(self, test_db, monkeypatch):
        """Failing to fetch the CSV must not mark the backfill as done."""
        import urllib.request

        from backend.airports.repository import AirportRepository
        from backend.database import get_global_setting

        monkeypatch.setattr(urllib.request, "urlretrieve", _raise_network_error)
        _seed_airport(test_db)

        AirportRepository().backfill_rank_columns()

        assert get_global_setting("airport_rank_backfill_done") != "1"

    def test_completed_backfill_is_flagged_and_not_repeated(self, test_db, monkeypatch):
        """Some stored airports are absent from the current CSV, so their `type`
        stays NULL — the flag is what stops a 12 MB re-read on every startup."""
        import urllib.request

        from backend.airports.repository import AirportRepository
        from backend.database import get_global_setting

        self._write_csv()
        _seed_airport(test_db, iata_code="ZZZ", name="Retired Airport", city_name="Nowhere")
        AirportRepository().load_from_csv_if_empty()
        AirportRepository().backfill_rank_columns()

        assert get_global_setting("airport_rank_backfill_done") == "1"

        # A second start must not touch the CSV at all
        monkeypatch.setattr(urllib.request, "urlretrieve", _raise_network_error)
        assert AirportRepository().backfill_rank_columns() == 0


class TestKeywordAliasSeeding:
    def test_seeds_aliases_from_csv_keywords(self, test_db):
        from pathlib import Path

        from backend.airports.repository import AirportRepository
        from backend.database import db_conn, get_db_path

        csv_path = Path(get_db_path()).parent / "airports.csv"
        csv_path.write_text(
            "iata_code,icao_code,type,name,municipality,iso_country,latitude_deg,"
            "longitude_deg,scheduled_service,keywords\n"
            "GOT,ESGG,large_airport,Göteborg Landvetter Airport,Göteborg,SE,"
            '57.66,12.27,yes,"Göteborg-Landvetter, Gothenburg"\n'
        )

        assert AirportRepository().seed_aliases_from_keywords() > 0

        with db_conn() as conn:
            row = conn.execute(
                "SELECT iata_code FROM airport_aliases WHERE alias = 'gothenburg'"
            ).fetchone()
        assert row["iata_code"] == "GOT"

    def test_does_not_override_a_curated_alias(self, test_db):
        from pathlib import Path

        from backend.airports.repository import AirportRepository
        from backend.database import db_conn, db_write, get_db_path

        with db_write() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO airport_aliases (alias, iata_code) VALUES ('warszawa', 'WAW')"
            )

        # Warsaw Modlin lists "Warszawa" in its keywords; WAW does not.
        csv_path = Path(get_db_path()).parent / "airports.csv"
        csv_path.write_text(
            "iata_code,icao_code,type,name,municipality,iso_country,latitude_deg,"
            "longitude_deg,scheduled_service,keywords\n"
            "WMI,EPMO,medium_airport,Warsaw Modlin Airport,Warsaw,PL,"
            "52.45,20.65,yes,Warszawa\n"
        )
        AirportRepository().seed_aliases_from_keywords()

        with db_conn() as conn:
            row = conn.execute(
                "SELECT iata_code FROM airport_aliases WHERE alias = 'warszawa'"
            ).fetchone()
        assert row["iata_code"] == "WAW"

    def test_skips_urls_and_short_tokens(self, test_db):
        from pathlib import Path

        from backend.airports.repository import AirportRepository
        from backend.database import db_conn, get_db_path

        csv_path = Path(get_db_path()).parent / "airports.csv"
        csv_path.write_text(
            "iata_code,icao_code,type,name,municipality,iso_country,latitude_deg,"
            "longitude_deg,scheduled_service,keywords\n"
            "VIE,LOWW,large_airport,Vienna Airport,Vienna,AT,48.11,16.56,yes,"
            '"https://en.wikipedia.org/wiki/Vienna, AT"\n'
        )
        AirportRepository().seed_aliases_from_keywords()

        with db_conn() as conn:
            aliases = {
                r["alias"] for r in conn.execute("SELECT alias FROM airport_aliases").fetchall()
            }
        assert not any(a.startswith("http") for a in aliases)
        assert "at" not in aliases

    def test_no_csv_seeds_nothing(self, test_db):
        from backend.airports.repository import AirportRepository

        assert AirportRepository().seed_aliases_from_keywords() == 0
