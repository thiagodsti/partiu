"""email_review/detect.py: the hints and excerpt shown for an email."""

import pytest

from backend.email_review import detect

from .helpers import seed_airports


class TestFlightNumbers:
    def test_real_flight_numbers_are_found(self):
        assert detect.flight_numbers("Voo O66175 e depois LA 8072") == ["O66175", "LA8072"]

    def test_css_colours_aircraft_types_and_single_digits_are_not(self):
        text = "h1 { color: #FF7020 } Airbus A320 and A330, ref 3D3, code 1E00"
        assert detect.flight_numbers(text) == []

    def test_leading_zeros_do_not_make_two_flights(self):
        assert detect.normalise_flight_number("TP 0788") == detect.normalise_flight_number("TP788")


class TestAirports:
    def test_months_currencies_and_words_are_not_airports(self, test_db):
        seed_airports(test_db)
        text = "GRU → FLN on 16 NOV, total 120 SEK, ida e volta (IDA)"
        assert detect.airport_codes(text) == ["GRU", "FLN"]


class TestClean:
    def test_css_and_leftover_markup_are_removed(self):
        text = (
            "a { color: red }\nHora de partida do voo <b\nstyle='color:#1b0088;'>LA4671</b>: 13:10"
        )
        cleaned = detect.clean(text)
        assert "color" not in cleaned and "LA4671" in cleaned and "<" not in cleaned


class TestHints:
    def test_dates_times_and_the_excerpt(self, test_db):
        seed_airports(test_db)
        body = "Ignore me\nVoo O66175\nFLN 16 NOV 15:40 → GRU 17:00\nCódigo da reserva: PVNQDY"
        h = detect.hints("Sua passagem", body)
        assert h["flight_numbers"] == ["O66175"]
        assert h["airports"] == ["FLN", "GRU"]
        assert "16 NOV" in h["dates"]
        assert h["times"] == ["15:40", "17:00"]
        assert "Ignore me" not in h["excerpt"]
        assert "Voo O66175" in h["excerpt"]

    def test_a_code_in_the_subject_wins_over_a_banner_word(self, test_db):
        h = detect.hints("Confirmação do pedido - JD8B6D", "ALUGUE UM CARRO\nVoo JJ3497")
        assert h["booking_reference"] == "JD8B6D"

    @pytest.mark.parametrize("word", ["OFERTAS"])
    def test_a_reference_that_also_appears_in_lower_case_is_a_word(self, test_db, word):
        body = f"Localizador: {word}\nVeja nossas Ofertas\nVoo LA8072"
        assert detect.hints("Sua reserva", body)["booking_reference"] is None
