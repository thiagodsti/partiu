"""Unit tests for SuggestionsService's helpers: where a request is about, and
whether a map hit is the place that was named."""

from unittest.mock import patch

from backend.suggestions.names import article_is_about, km, latin, same_name
from backend.suggestions.service import Where, _city_of_stay, _locate_one

CHENGDU = Where("Chengdu", 30.6598, 104.0633, "CN", None, None, None, None)
LISBOA = Where("Lisboa", 38.7223, -9.1393, "PT", None, None, None, None)


def _locate(name, hits, where=LISBOA):
    with patch("backend.suggestions.service.photon.search_places", return_value=hits):
        return _locate_one(name, where)


class TestCityOfStay:
    def test_two_parts_without_a_country_is_the_city_not_the_street(self):
        stay = {"name": "Calle Fernando poo 16", "address": "Calle Fernando Poo 16, Madrid"}
        assert _city_of_stay(stay) == "Madrid"

    def test_the_country_is_dropped(self):
        stay = {"name": "H", "address": "No. 7 Qianjing Hutong, Xicheng District, Beijing, China"}
        assert _city_of_stay(stay) == "Beijing"

    def test_a_known_city_wins_over_a_district_after_it(self):
        stay = {"name": "Flat", "address": "Calle Fernando Poo 16, Arganzuela, Madrid"}
        assert _city_of_stay(stay, lambda names: {"madrid"} & set(names)) == "Madrid"

    def test_only_a_street_falls_back_to_the_name(self):
        assert _city_of_stay({"name": "Casa Azul", "address": "Rua das Flores 10"}) == "Casa Azul"

    def test_the_city_behind_a_postcode(self):
        stay = {"name": "Casa", "address": "Rua das Flores 10, 1200-195 Lisboa, Portugal"}
        assert _city_of_stay(stay) == "Lisboa"

    def test_no_address_falls_back_to_the_name(self):
        assert _city_of_stay({"name": "Hotel Lisboa", "address": None}) == "Hotel Lisboa"


class TestNames:
    def test_lisbon_to_belem_is_a_few_km(self):
        assert 5 < km((38.7223, -9.1393), (38.6916, -9.2160)) < 9

    def test_a_different_place_nearby_is_not_the_one_named(self):
        # Photon's actual answer for this name in Lisbon.
        assert not same_name("Casa de Pasto Sol e Pesca", "Vinhos e Petiscos")

    def test_the_same_place_in_another_form(self):
        assert same_name("Time Out Market", "Time Out Market Lisboa")
        assert same_name("Torre de Belém", "Belém Tower")
        assert same_name("Museu Calouste Gulbenkian", "Calouste Gulbenkian Museum")

    def test_generic_words_do_not_make_a_match(self):
        assert not same_name("Restaurante do Bairro", "Restaurante Galeto")

    def test_latin_names_with_accents_stay_latin(self):
        assert latin("Torre de Belém") and latin("Kuanzhai Alley")
        assert not latin("四川博物院") and not latin("Эрмитаж")

    def test_an_article_title_about_the_place(self):
        assert article_is_about("Time Out Market", "Time Out Market Lisboa")
        assert article_is_about("Torre de Belém", "Belém Tower")
        assert article_is_about("Mosteiro dos Jerónimos", "Jerónimos Monastery")

    def test_the_district_a_place_is_named_after_is_not_its_article(self):
        assert not article_is_about("Café Chiado", "Chiado")

    def test_a_name_inside_another_word_is_not_contained(self):
        assert not article_is_about("Bar", "Barcelona")


class TestLocateOne:
    def test_a_name_only_in_the_local_script_reads_in_the_models_words(self):
        found = _locate(
            "Sichuan Museum", [{"name": "四川博物院", "lat": 30.66, "lon": 104.03}], CHENGDU
        )
        assert found is not None
        assert found["place_name"] == "Sichuan Museum" and found["local_name"] == "四川博物院"

    def test_a_lower_ranked_hit_in_another_script_is_not_trusted(self):
        hits = [
            {"name": "Unrelated Hotel", "lat": 30.6, "lon": 104.0},
            {"name": "四川博物院", "lat": 30.66, "lon": 104.03},
        ]
        assert _locate("Sichuan Museum", hits, CHENGDU) is None

    def test_a_fuzzy_namesake_is_refused(self):
        hits = [{"name": "Vinhos e Petiscos", "lat": 38.71, "lon": -9.14}]
        assert _locate("Casa de Pasto Sol e Pesca", hits) is None

    def test_a_namesake_on_another_continent_is_refused(self):
        assert (
            _locate("Torre de Belém", [{"name": "Torre de Belém", "lat": -23.5, "lon": -46.6}])
            is None
        )
