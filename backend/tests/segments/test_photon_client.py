"""Tests for backend.integrations.photon.client — station type-ahead lookup.

The response fixtures below are trimmed from real photon.komoot.io answers, so
the field-name quirks under test (a Chinese station whose `city` is missing but
whose `county` is set; the same station returned as two nearby OSM nodes) are
the ones the live API actually produces.
"""

from unittest.mock import MagicMock, patch

import pytest


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
