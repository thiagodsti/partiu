"""Placing an imported stay on the map: only an answer the booking backs up.

Photon is replaced by canned answers — real ones, recorded from a self-hosted
instance on 2026-11-28 for the bookings that went wrong.
"""

from unittest.mock import patch

from backend.sync.stay_geocode import geocode_stay, local_street

CHENGDU = {
    "name": "IntercityHotel Chengdu Kuanzhai Alley",
    "address": "No. 1 Xiaotong Lane, Qingyang District, Chengdu, Sichuan, China",
    "local_address": "成都市青羊区小通巷1号",
    "city": "Chengdu",
    "country_code": None,
}


def _hit(name, city, cc, lat, lon, country=""):
    return {
        "name": name,
        "city": city,
        "countrycode": cc,
        "country": country,
        "lat": lat,
        "lon": lon,
        "address": "",
    }


def _geocode(stay, answers):
    def search(query, kind=None, limit=8, near=None):
        return answers.get(query, [])

    with patch("backend.sync.stay_geocode.photon.search_places", side_effect=search) as s:
        return geocode_stay(stay), [c.args[0] for c in s.call_args_list]


class TestLocalStreet:
    def test_the_street_out_of_a_chinese_address(self):
        assert local_street("成都市青羊区小通巷1号") == "小通巷"
        assert local_street("北京西城区前井胡同7号") == "前井胡同"

    def test_a_street_named_market_is_not_cut_at_its_own_city_character(self):
        assert local_street("西安市莲湖区西羊市18号") == "西羊市"

    def test_a_latin_line_is_not_a_local_address(self):
        assert local_street("1 Example Street, Porto") is None
        assert local_street(None) is None


class TestChengdu:
    def test_the_english_address_answers_wrongly_and_the_local_street_rightly(self):
        (lat, lon, cc), asked = _geocode(
            CHENGDU,
            {
                CHENGDU["address"]: [
                    # Same city, wrong place: shares no word with "Xiaotong Lane".
                    _hit("RENJU EAST LAKE ISLAND", "Chengdu", "CN", 30.6177, 104.0896),
                    # Another country altogether.
                    _hit("Forte Hotel Changhua", "Changhua City", "TW", 24.0691, 120.5452),
                ],
                "小通巷": [_hit("小通巷", "Chengdu", "CN", 30.6702, 104.0509)],
            },
        )
        assert (lat, lon, cc) == (30.6702, 104.0509, "CN")
        assert asked == [CHENGDU["address"], "小通巷"]

    def test_another_hotel_in_the_same_alley_is_not_this_one(self):
        stay = {**CHENGDU, "address": None, "local_address": None}
        (lat, _, _), _ = _geocode(
            stay,
            {
                "IntercityHotel Chengdu Kuanzhai Alley, Chengdu": [
                    _hit(
                        "Nostalgia S Hotel (Chengdu KuanZhai Alley)", "Chengdu", "CN", 30.66, 104.04
                    )
                ]
            },
        )
        # "Kuanzhai" and "Alley" are shared; the hotel's own name is not.
        assert lat is None

    def test_the_hotel_found_by_its_own_name(self):
        stay = {"name": "Nanfeng Hotel (Xi'an Zhonggulou Branch)", "address": None, "city": "Xi'an"}
        (lat, _, _), _ = _geocode(
            stay,
            # Asked without the branch note in brackets, which finds nothing.
            {"Nanfeng Hotel, Xi'an": [_hit("Nanfeng Hotel", "Xi'an", "CN", 34.2572, 108.9241)]},
        )
        assert lat == 34.2572


class TestStreetNames:
    def test_rue_is_not_what_names_a_street(self):
        stay = {
            "name": "Flat",
            "address": "10 Rue de Rivoli, Paris",
            "city": None,
            "country_code": "FR",
        }
        wrong = _hit("Rue de la Paix", "Paris", "FR", 48.869, 2.331)
        right = _hit("Rue de Rivoli", "Paris", "FR", 48.856, 2.355)
        (lat, _, _), _ = _geocode(stay, {stay["address"]: [wrong, right]})
        assert lat == 48.856

    def test_des_is_not_what_names_a_street(self):
        stay = {
            "name": "Flat",
            "address": "10 Rue des Martyrs, Paris",
            "city": None,
            "country_code": "FR",
        }
        wrong = _hit("Rue des Archives", "Paris", "FR", 48.859, 2.357)
        right = _hit("Rue des Martyrs", "Paris", "FR", 48.880, 2.339)
        (lat, _, _), _ = _geocode(stay, {stay["address"]: [wrong, right]})
        assert lat == 48.880


class TestWhereChecks:
    def test_a_hit_in_a_city_the_booking_never_names_is_refused(self):
        stay = {
            "name": "Casa",
            "address": "Rua das Flores 10, Porto",
            "city": None,
            "country_code": None,
        }
        (lat, _, _), _ = _geocode(
            stay, {stay["address"]: [_hit("Rua das Flores", "Taipei", "TW", 25.0, 121.5)]}
        )
        assert lat is None

    def test_a_country_that_contradicts_the_booking_is_refused(self):
        stay = {
            "name": "Casa",
            "address": "Rua das Flores 10, Porto",
            "city": None,
            "country_code": "PT",
        }
        (lat, _, _), _ = _geocode(
            stay, {stay["address"]: [_hit("Rua das Flores", "Porto", "BR", -23.0, -46.0)]}
        )
        assert lat is None

    def test_the_bookings_country_code_vouches_for_a_city_spelled_otherwise(self):
        # Photon answers in English ("Lisbon"); the address says "Lisboa".
        stay = {
            "name": "Flat",
            "address": "Rua das Flores 10, Lisboa",
            "city": None,
            "country_code": "PT",
        }
        (lat, _, cc), _ = _geocode(
            stay, {stay["address"]: [_hit("Rua das Flores", "Lisbon", "PT", 38.71, -9.14)]}
        )
        assert (lat, cc) == (38.71, "PT")

    def test_a_street_written_slightly_differently_still_matches(self):
        stay = {
            "name": "Calle Fernando poo 16",
            "address": "Calle Fernando Poo 16, Madrid",
            "city": None,
        }
        (lat, _, cc), _ = _geocode(
            stay,
            {stay["address"]: [_hit("Calle de Fernando Poo", "Madrid", "ES", 40.3985, -3.6999)]},
        )
        assert (lat, cc) == (40.3985, "ES")


def test_nothing_that_fits_leaves_the_stay_off_the_map():
    (lat, lon, cc), asked = _geocode(CHENGDU, {})
    assert (lat, lon, cc) == (None, None, None)
    assert asked == [CHENGDU["address"], "小通巷", f"{CHENGDU['name']}, Chengdu"]


def test_a_geocoder_outage_is_not_an_error():
    with patch("backend.sync.stay_geocode.photon.search_places", side_effect=OSError("down")):
        assert geocode_stay(CHENGDU) == (None, None, None)
