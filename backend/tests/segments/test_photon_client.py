"""Tests for backend.integrations.photon.client — station type-ahead lookup.

The response fixtures below are trimmed from real photon.komoot.io answers, so
the field-name quirks under test (a Chinese station whose `city` is missing but
whose `county` is set; the same station returned as two nearby OSM nodes) are
the ones the live API actually produces.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear_photon_cache():
    """The client's response cache is process-global, so a warmed entry would
    otherwise leak between tests — two reverse lookups a few metres apart share
    a rounded key, which is exactly what the cache is for and exactly what makes
    tests order-dependent without this."""
    from backend.integrations.photon import client

    client.clear_cache()
    yield
    client.clear_cache()


def _feature(name, lon, lat, **props):
    return {
        "type": "Feature",
        "properties": {"name": name, "osm_id": abs(hash(name)) % 10**9, **props},
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
    }


def _mock_response(features):
    response = MagicMock()
    response.json.return_value = {"features": features}
    response.raise_for_status.return_value = None
    return response


@pytest.fixture
def photon_enabled(monkeypatch):
    import backend.config as cfg

    monkeypatch.setattr(cfg.settings, "PHOTON_URL", "https://photon.example")


class TestSearchStations:
    def test_parses_a_station(self, photon_enabled):
        from backend.integrations.photon import client

        features = [
            _feature(
                "Xi'an North Railway Station",
                108.9339348,
                34.3775583,
                city="Xi'an",
                country="China",
                countrycode="CN",
            )
        ]
        with patch.object(client.httpx, "get", return_value=_mock_response(features)):
            results = client.search_stations("xi'an north", "train")

        assert len(results) == 1
        assert results[0]["name"] == "Xi'an North Railway Station"
        assert results[0]["city"] == "Xi'an"
        assert results[0]["lat"] == 34.3775583
        assert results[0]["lon"] == 108.9339348

    def test_deduplicates_the_same_station_mapped_twice(self, photon_enabled):
        """Large stations are frequently several OSM nodes a few metres apart —
        Xi'an North comes back twice from the live API."""
        from backend.integrations.photon import client

        features = [
            _feature("Xi'an North Railway Station", 108.9339348, 34.3775583, city="Xi'an"),
            _feature("Xi'an North Railway Station", 108.9341245, 34.3810219, city="Xi'an"),
        ]
        with patch.object(client.httpx, "get", return_value=_mock_response(features)):
            results = client.search_stations("xi'an north", "train")

        assert len(results) == 1

    def test_same_name_in_different_cities_is_kept(self, photon_enabled):
        from backend.integrations.photon import client

        features = [
            _feature("Central Station", 4.9, 52.3, city="Amsterdam"),
            _feature("Central Station", 11.0, 49.4, city="Nuremberg"),
        ]
        with patch.object(client.httpx, "get", return_value=_mock_response(features)):
            results = client.search_stations("central station", "train")

        assert len(results) == 2

    def test_falls_back_through_city_fields(self, photon_enabled):
        """Photon fills the place fields inconsistently by country; many Chinese
        stations have no `city` but do have `county`."""
        from backend.integrations.photon import client

        features = [_feature("Some Station", 113.8, 27.6, county="Shangli", state="Jiangxi")]
        with patch.object(client.httpx, "get", return_value=_mock_response(features)):
            results = client.search_stations("some station", "train")

        assert results[0]["city"] == "Shangli"

    def test_requests_english_names_and_the_right_osm_tag(self, photon_enabled):
        """`lang=en` is load-bearing: without it Photon answers `北京西` and
        Latin-script queries barely match."""
        from backend.integrations.photon import client

        with patch.object(client.httpx, "get", return_value=_mock_response([])) as mock_get:
            client.search_stations("beijing west", "train")

        params = dict(mock_get.call_args.kwargs["params"])
        assert params["lang"] == "en"
        sent = mock_get.call_args.kwargs["params"]
        assert ("osm_tag", "railway:station") in sent

    def test_bus_kind_uses_bus_tags(self, photon_enabled):
        from backend.integrations.photon import client

        with patch.object(client.httpx, "get", return_value=_mock_response([])) as mock_get:
            client.search_stations("zob", "bus")

        sent = mock_get.call_args.kwargs["params"]
        assert ("osm_tag", "amenity:bus_station") in sent
        assert ("osm_tag", "railway:station") not in sent

    def test_unknown_kind_searches_every_station_type(self, photon_enabled):
        from backend.integrations.photon import client

        with patch.object(client.httpx, "get", return_value=_mock_response([])) as mock_get:
            client.search_stations("somewhere", None)

        sent = mock_get.call_args.kwargs["params"]
        assert ("osm_tag", "railway:station") in sent
        assert ("osm_tag", "amenity:bus_station") in sent

    def test_respects_the_limit(self, photon_enabled):
        from backend.integrations.photon import client

        features = [
            _feature(f"Station {i}", float(i), float(i), city=f"City {i}") for i in range(20)
        ]
        with patch.object(client.httpx, "get", return_value=_mock_response(features)):
            results = client.search_stations("station", "train", limit=3)

        assert len(results) == 3

    def test_network_failure_returns_empty_list(self, photon_enabled):
        """The geocoder is optional — a failure must not propagate, so the form
        can fall back to plain free-text entry."""
        from backend.integrations.photon import client

        with patch.object(client.httpx, "get", side_effect=OSError("connection refused")):
            assert client.search_stations("beijing", "train") == []

    def test_malformed_feature_is_skipped(self, photon_enabled):
        from backend.integrations.photon import client

        features = [
            {"properties": {"name": "No geometry"}, "geometry": {}},
            {"properties": {}, "geometry": {"coordinates": [1.0, 2.0]}},  # no name
            _feature("Good Station", 3.0, 4.0, city="Somewhere"),
        ]
        with patch.object(client.httpx, "get", return_value=_mock_response(features)):
            results = client.search_stations("station", "train")

        assert [r["name"] for r in results] == ["Good Station"]

    def test_blank_query_makes_no_request(self, photon_enabled):
        from backend.integrations.photon import client

        with patch.object(client.httpx, "get") as mock_get:
            assert client.search_stations("   ", "train") == []
        mock_get.assert_not_called()

    def test_disabled_when_url_is_blank(self, monkeypatch):
        import backend.config as cfg
        from backend.integrations.photon import client

        monkeypatch.setattr(cfg.settings, "PHOTON_URL", "")
        with patch.object(client.httpx, "get") as mock_get:
            assert client.search_stations("beijing", "train") == []
        mock_get.assert_not_called()
        assert client.is_configured() is False


class TestPlaceSearch:
    """The accommodation/address search behind the stay picker."""

    def test_stay_kind_uses_accommodation_tags(self):
        from unittest.mock import patch

        from backend.integrations.photon import client

        with (
            patch.object(client.settings, "PHOTON_URL", "http://photon.test"),
            patch.object(client, "_fetch", return_value=[]) as fetch,
        ):
            client.search_places("avenida palace", "stay")

        tags = [v for k, v in fetch.call_args_list[0].args[0] if k == "osm_tag"]
        assert "tourism:hotel" in tags
        assert "tourism:apartment" in tags
        # Station tags must not leak in, or a train station lands in the hotel list.
        assert "railway:station" not in tags

    def test_stay_falls_back_to_an_untagged_address_search(self):
        """A private rental is usually not in OSM as a venue, so a thin tagged
        result set triggers a second, untagged pass over plain addresses."""
        from unittest.mock import patch

        from backend.integrations.photon import client

        with (
            patch.object(client.settings, "PHOTON_URL", "http://photon.test"),
            patch.object(client, "_fetch", return_value=[]) as fetch,
        ):
            client.search_places("rua garrett 20", "stay")

        assert fetch.call_count == 2
        second_call_tags = [v for k, v in fetch.call_args_list[1].args[0] if k == "osm_tag"]
        assert second_call_tags == []

    def test_a_full_tagged_result_set_costs_one_request(self):
        from unittest.mock import patch

        from backend.integrations.photon import client

        features = [
            {
                "properties": {"name": f"Hotel {i}", "city": "Lisbon", "osm_key": "tourism"},
                "geometry": {"coordinates": [-9.14, 38.71 + i / 100]},
            }
            for i in range(5)
        ]
        with (
            patch.object(client.settings, "PHOTON_URL", "http://photon.test"),
            patch.object(client, "_fetch", return_value=features) as fetch,
        ):
            client.search_places("hotel", "stay")

        assert fetch.call_count == 1

    def test_station_search_never_returns_accommodation(self):
        """`search_stations` is the segments endpoint; a 'stay' reaching it must
        not swap the station tags for hotel ones."""
        from unittest.mock import patch

        from backend.integrations.photon import client

        with (
            patch.object(client.settings, "PHOTON_URL", "http://photon.test"),
            patch.object(client, "_fetch", return_value=[]) as fetch,
        ):
            client.search_stations("something", "stay")

        tags = [v for k, v in fetch.call_args_list[0].args[0] if k == "osm_tag"]
        assert "tourism:hotel" not in tags
        assert "railway:station" in tags

    def test_results_are_classified_and_carry_an_address(self):
        from unittest.mock import patch

        from backend.integrations.photon import client

        features = [
            {
                "properties": {
                    "name": "Hotel Avenida Palace",
                    "street": "Rua 1º de Dezembro",
                    "housenumber": "123",
                    "postcode": "1200-359",
                    "city": "Lisbon",
                    "countrycode": "PT",
                    "osm_key": "tourism",
                },
                "geometry": {"coordinates": [-9.1409, 38.7145]},
            },
            {
                "properties": {
                    "name": "Rua Garrett",
                    "street": "Rua Garrett",
                    "city": "Lisbon",
                    "countrycode": "PT",
                    "osm_key": "place",
                },
                "geometry": {"coordinates": [-9.1420, 38.7108]},
            },
        ]
        with (
            patch.object(client.settings, "PHOTON_URL", "http://photon.test"),
            patch.object(client, "_fetch", return_value=features),
        ):
            results = client.search_places("garrett", "stay")

        assert results[0]["category"] == "place"
        assert results[0]["address"] == "Rua 1º de Dezembro 123, 1200-359, Lisbon"
        assert results[0]["countrycode"] == "PT"
        assert results[1]["category"] == "address"

    def test_disabled_geocoder_returns_empty(self):
        from unittest.mock import patch

        from backend.integrations.photon import client

        with patch.object(client.settings, "PHOTON_URL", ""):
            assert client.search_places("hotel", "stay") == []


class TestReverseCountry:
    def test_returns_the_country_code(self):
        from unittest.mock import patch

        from backend.integrations.photon import client

        features = [{"properties": {"countrycode": "se", "name": "Malmö central"}}]
        with (
            patch.object(client.settings, "PHOTON_URL", "http://photon.test"),
            patch.object(client, "_fetch", return_value=features),
        ):
            assert client.reverse_country(55.6091, 13.0007) == "SE"

    def test_returns_none_rather_than_guessing(self):
        """No answer means unknown. A wrong country shown as a visited fact is
        worse than a missing one — see the docstring for the measurement."""
        from unittest.mock import patch

        from backend.integrations.photon import client

        with (
            patch.object(client.settings, "PHOTON_URL", "http://photon.test"),
            patch.object(client, "_fetch", return_value=[]),
        ):
            assert client.reverse_country(55.6091, 13.0007) is None

    def test_returns_none_without_a_geocoder(self):
        from unittest.mock import patch

        from backend.integrations.photon import client

        with patch.object(client.settings, "PHOTON_URL", ""):
            assert client.reverse_country(55.6091, 13.0007) is None


class TestResponseCache:
    """The picker fires a request per debounced keystroke against a public,
    rate-limited service, so repeated prefixes must not each cost a round trip."""

    def test_a_repeated_search_does_not_hit_the_network_twice(self):
        from unittest.mock import patch

        from backend.integrations.photon import client

        features = [
            {
                "properties": {
                    "name": "Oslo Central Station",
                    "city": "Oslo",
                    "osm_key": "railway",
                },
                "geometry": {"coordinates": [10.75, 59.91]},
            }
        ]
        with (
            patch.object(client.settings, "PHOTON_URL", "http://photon.test"),
            patch.object(client, "_fetch", return_value=features) as fetch,
        ):
            first = client.search_places("oslo s", "train")
            second = client.search_places("oslo s", "train")

        assert fetch.call_count == 1
        assert first == second

    def test_the_cache_is_case_insensitive(self):
        from unittest.mock import patch

        from backend.integrations.photon import client

        with (
            patch.object(client.settings, "PHOTON_URL", "http://photon.test"),
            patch.object(client, "_fetch", return_value=[]) as fetch,
        ):
            client.search_places("Oslo S", "train")
            client.search_places("oslo s", "train")

        assert fetch.call_count == 1

    def test_different_kinds_do_not_share_an_entry(self):
        """A hotel search and a station search for the same text are different
        questions — sharing a cache entry would put hotels in the station list."""
        from unittest.mock import patch

        from backend.integrations.photon import client

        with (
            patch.object(client.settings, "PHOTON_URL", "http://photon.test"),
            patch.object(client, "_fetch", return_value=[]) as fetch,
        ):
            client.search_places("central", "train")
            client.search_places("central", "stay")

        assert fetch.call_count > 1

    def test_a_returned_list_cannot_corrupt_the_cached_entry(self):
        from unittest.mock import patch

        from backend.integrations.photon import client

        features = [
            {
                "properties": {
                    "name": "Oslo Central Station",
                    "city": "Oslo",
                    "osm_key": "railway",
                },
                "geometry": {"coordinates": [10.75, 59.91]},
            }
        ]
        with (
            patch.object(client.settings, "PHOTON_URL", "http://photon.test"),
            patch.object(client, "_fetch", return_value=features),
        ):
            first = client.search_places("oslo s", "train")
            first[0]["name"] = "MUTATED"
            second = client.search_places("oslo s", "train")

        assert second[0]["name"] == "Oslo Central Station"

    def test_entries_expire(self):
        from unittest.mock import patch

        from backend.integrations.photon import client

        with (
            patch.object(client.settings, "PHOTON_URL", "http://photon.test"),
            patch.object(client, "_CACHE_TTL_SECONDS", -1),
            patch.object(client, "_fetch", return_value=[]) as fetch,
        ):
            client.search_places("oslo s", "train")
            client.search_places("oslo s", "train")

        assert fetch.call_count == 2

    def test_the_cache_is_bounded(self):
        from unittest.mock import patch

        from backend.integrations.photon import client

        with (
            patch.object(client.settings, "PHOTON_URL", "http://photon.test"),
            patch.object(client, "_CACHE_MAX_ENTRIES", 3),
            patch.object(client, "_fetch", return_value=[]),
        ):
            for i in range(10):
                client.search_places(f"query {i}", "train")

        assert len(client._cache) <= 3

    def test_reverse_lookups_are_cached_and_rounded(self):
        """The backfill walks many places; two points in the same city round to
        one key, and they are certainly in the same country."""
        from unittest.mock import patch

        from backend.integrations.photon import client

        features = [{"properties": {"countrycode": "NO"}}]
        with (
            patch.object(client.settings, "PHOTON_URL", "http://photon.test"),
            patch.object(client, "_fetch", return_value=features) as fetch,
        ):
            assert client.reverse_country(59.9107, 10.7522) == "NO"
            assert client.reverse_country(59.9109, 10.7523) == "NO"

        assert fetch.call_count == 1

    def test_an_unresolvable_coordinate_is_not_retried(self):
        from unittest.mock import patch

        from backend.integrations.photon import client

        with (
            patch.object(client.settings, "PHOTON_URL", "http://photon.test"),
            patch.object(client, "_fetch", return_value=[]) as fetch,
        ):
            assert client.reverse_country(0.0, 0.0) is None
            assert client.reverse_country(0.0, 0.0) is None

        assert fetch.call_count == 1
