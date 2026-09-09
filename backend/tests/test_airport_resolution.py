"""
Tests for airport name → IATA resolution (backend.parsers.shared.resolve_iata).

These are regression tests for a class of silent corruption: the resolver used
to run an unanchored ``LIKE '%term%'`` with ``LIMIT 1`` and no ordering, so
whichever row SQLite returned first won.  That turned "STOCKHOLM" into Nyköping
(NYO), "SAO PAULO" into Ponta Delgada (PDL, via "João **Paulo** II Airport"),
and the bare word "Airport" into Utirik (UTK) — each of them a real, valid IATA
code, and therefore invisible to every downstream check.

The rule now is that resolution must be *confident or absent*: returning ''
lets the caller drop a leg, which is recoverable, while returning the wrong
airport is not.
"""

import sqlite3

import pytest

from backend.utils import fold_text

# (iata, name, city, country, type, scheduled_service)
_AIRPORTS = [
    # Stockholm: the metro area's airports, including the trap
    ("ARN", "Stockholm-Arlanda Airport", "Stockholm", "SE", "large_airport", 1),
    ("NYO", "Stockholm Skavsta Airport", "Nyköping", "SE", "medium_airport", 1),
    ("BMA", "Stockholm-Bromma Airport", "Stockholm", "SE", "medium_airport", 1),
    ("SMP", "Stockholm Landing Strip", "Stockholm", "PG", "small_airport", 0),
    # São Paulo, and the airport whose *name* contains "Paulo"
    ("GRU", "São Paulo/Guarulhos International Airport", "São Paulo", "BR", "large_airport", 1),
    ("PDL", "João Paulo II Airport", "Ponta Delgada", "PT", "medium_airport", 1),
    ("CGH", "Congonhas Airport", "São Paulo", "BR", "medium_airport", 1),
    # Accented names that ASCII input has to reach
    ("FLN", "Hercílio Luz International Airport", "Florianópolis", "BR", "large_airport", 1),
    ("DUS", "Düsseldorf Airport", "Düsseldorf", "DE", "large_airport", 1),
    # Helsinki: a heliport shares the city name with the real airport
    ("HEL", "Helsinki Vantaa Airport", "Helsinki (Vantaa)", "FI", "large_airport", 1),
    ("HEN", "Hernesaari Heliport", "Helsinki", "FI", "heliport", 0),
    # Faro: same city name in two countries, only one with scheduled service
    ("FAO", "Faro - Gago Coutinho International Airport", "Faro", "PT", "large_airport", 1),
    ("ZFA", "Faro Airport", "Faro", "CA", "small_airport", 0),
    ("LIS", "Humberto Delgado Airport", "Lisbon", "PT", "large_airport", 1),
    # A generic word appears in nearly every airport name
    ("UTK", "Utirik Airport", "Utirik Island", "MH", "small_airport", 0),
]


@pytest.fixture(scope="module")
def airports_db(tmp_path_factory):
    """A reference table shaped like the real one, including its ambiguities."""
    import backend.config as cfg_module
    import backend.database as db_module

    db_path = str(tmp_path_factory.mktemp("resolve_iata_db") / "test.db")
    original = db_module.settings.DB_PATH
    db_module.settings.DB_PATH = db_path
    cfg_module.settings.DB_PATH = db_path

    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE airports (iata_code TEXT PRIMARY KEY, name TEXT, city_name TEXT,"
        " country_code TEXT, type TEXT, scheduled_service INTEGER,"
        " name_folded TEXT, city_folded TEXT)"
    )
    conn.execute("CREATE TABLE airport_aliases (alias TEXT PRIMARY KEY, iata_code TEXT NOT NULL)")
    conn.executemany(
        "INSERT INTO airports VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(i, n, c, cc, t, s, fold_text(n), fold_text(c)) for i, n, c, cc, t, s in _AIRPORTS],
    )
    conn.commit()
    conn.close()

    from backend.parsers.shared import is_valid_iata, resolve_iata

    resolve_iata.cache_clear()
    is_valid_iata.cache_clear()

    yield db_path

    db_module.settings.DB_PATH = original
    cfg_module.settings.DB_PATH = original
    resolve_iata.cache_clear()
    is_valid_iata.cache_clear()


def resolve(name: str) -> str:
    from backend.parsers.shared import resolve_iata

    return resolve_iata(name)


class TestPicksTheAirportATravellerMeans:
    def test_stockholm_is_arlanda_not_nykoping(self, airports_db):
        assert resolve("STOCKHOLM") == "ARN"

    def test_stockholm_arlanda_full_name(self, airports_db):
        assert resolve("STOCKHOLM ARLANDA") == "ARN"

    def test_sao_paulo_is_guarulhos_not_ponta_delgada(self, airports_db):
        assert resolve("SAO PAULO") == "GRU"

    def test_sao_paulo_with_airport_name(self, airports_db):
        assert resolve("SAO PAULO GUARULHOS INTL") == "GRU"

    def test_ponta_delgada_still_resolves_to_itself(self, airports_db):
        assert resolve("Ponta Delgada") == "PDL"

    def test_nykoping_still_resolves_to_itself(self, airports_db):
        assert resolve("Nykoping") == "NYO"

    def test_prefers_airport_over_heliport(self, airports_db):
        assert resolve("Helsinki") == "HEL"

    def test_prefers_scheduled_service_over_namesake(self, airports_db):
        assert resolve("Faro") == "FAO"

    def test_ignores_disused_landing_strip(self, airports_db):
        assert resolve("Stockholm") != "SMP"


class TestAccentFolding:
    def test_unaccented_query_matches_accented_city(self, airports_db):
        assert resolve("FLORIANOPOLIS") == "FLN"

    def test_unaccented_query_matches_accented_name(self, airports_db):
        assert resolve("Dusseldorf") == "DUS"

    def test_accented_query_still_matches(self, airports_db):
        assert resolve("Düsseldorf") == "DUS"

    def test_airport_named_differently_from_its_city(self, airports_db):
        assert resolve("FLORIANOPOLIS HERCILIO LUZ INTL") == "FLN"


class TestRefusesToGuess:
    @pytest.mark.parametrize(
        "noise",
        ["AIRPORT", "Terminal", "Fare basis", "Duration", "Class", "Booking status", "Flight"],
    )
    def test_generic_words_resolve_to_nothing(self, airports_db, noise):
        assert resolve(noise) == ""

    def test_unknown_place_resolves_to_nothing(self, airports_db):
        assert resolve("Nowhereville") == ""

    def test_empty_string(self, airports_db):
        assert resolve("") == ""


class TestExplicitCodes:
    def test_trailing_code_wins(self, airports_db):
        assert resolve("Stockholm Arlanda ARN") == "ARN"

    def test_bare_metro_city_code_maps_to_its_main_airport(self, airports_db):
        # STO is a *city* code covering ARN/BMA/NYO, not an airport in its own right
        assert resolve("STO") == "ARN"

    def test_bare_airport_code_passes_through(self, airports_db):
        assert resolve("LIS") == "LIS"


class TestAliasTable:
    def test_curated_alias_is_used(self, airports_db):
        from backend.database import db_write
        from backend.parsers.shared import resolve_iata

        with db_write() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO airport_aliases (alias, iata_code) VALUES (?, ?)",
                ("lisbon portela", "LIS"),
            )
        resolve_iata.cache_clear()
        assert resolve("lisbon portela") == "LIS"
