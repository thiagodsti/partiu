"""Tests for backend.integrations.llm.parser (the optional Ollama fallback).

Ollama itself is never called: _call_ollama is patched, or urlopen is, and the
tests look at what would be sent and at what is done with the answer.
"""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest


def _email(body="", html=None, date=None):
    from backend.parsers.email_connector import EmailMessage

    return EmailMessage(
        message_id="<t@example>",
        sender="Azul <no-reply@voeazul.com.br>",
        subject="Reserva TESTR5 realizada com sucesso",
        body=body,
        date=date,
        html_body=html,
    )


def _answer(**leg):
    base = {
        "flight_number": "AD4849",
        "dep_airport": "VCP",
        "arr_airport": "FLN",
        "dep_datetime": "2026-03-02T13:20:00",
        "dep_date": "2026-03-02",
        "airline_code": "AD",
    }
    base.update(leg)
    return json.dumps({"has_flight": True, "booking_reference": "TESTR5", "flights": [base]})


def _run(answer, email=None):
    from backend.integrations.llm import parser

    with (
        patch.object(parser, "llm_available", return_value=True),
        patch("backend.config.settings.OLLAMA_URL", "http://ollama:11434"),
        patch.object(parser, "_call_ollama", return_value=answer) as call,
    ):
        return parser.llm_extract_flights(email or _email(body="Voo 4849 VCP FLN")), call


class TestSchema:
    def test_every_leg_must_carry_route_and_date(self):
        from backend.integrations.llm.parser import _FLIGHT_SCHEMA

        required = _FLIGHT_SCHEMA["properties"]["flights"]["items"]["required"]
        for field in ("flight_number", "dep_airport", "arr_airport", "dep_date"):
            assert field in required


class TestRequest:
    def _payload(self, **kwargs):
        from backend.integrations.llm.parser import _call_ollama

        resp = MagicMock()
        resp.read.return_value = json.dumps({"message": {"content": "{}"}}).encode()
        resp.__enter__.return_value = resp
        with patch("urllib.request.urlopen", return_value=resp) as urlopen:
            _call_ollama("prompt", "qwen3:4b-instruct", "http://ollama:11434", **kwargs)
        return json.loads(urlopen.call_args.args[0].data)

    def test_context_window_comes_from_settings(self):
        with patch("backend.config.settings.OLLAMA_NUM_CTX", 8192):
            assert self._payload()["options"]["num_ctx"] == 8192

    def test_context_window_can_be_overridden(self):
        assert self._payload(num_ctx=16384)["options"]["num_ctx"] == 16384

    def test_prompt_carries_the_email_date_not_today(self):
        _, call = _run(_answer(), _email(body="Voo 4849", date=datetime(2025, 11, 3, tzinfo=UTC)))
        prompt = call.call_args.args[0]
        assert "Email date: 2025-11-03" in prompt


class TestAnswerRepair:
    def test_digits_only_flight_number_gets_the_airline_code(self):
        flights, _ = _run(_answer(flight_number="4849"))
        assert [f["flight_number"] for f in flights] == ["AD4849"]

    def test_prefixed_flight_number_is_left_alone(self):
        flights, _ = _run(_answer(flight_number="AD4849", airline_code="LA"))
        assert [f["flight_number"] for f in flights] == ["AD4849"]

    def test_digits_without_airline_code_still_fail_validation(self):
        flights, _ = _run(_answer(flight_number="4849", airline_code=None))
        assert flights == []


class TestBody:
    def test_manage_booking_above_the_itinerary_does_not_cut_it(self):
        from backend.integrations.llm.parser import build_llm_body

        body = build_llm_body(
            _email(body="Hi, booking confirmed.\nManage your booking\nVY1266 ARN 06:50 BCN 10:15")
        )
        assert "VY1266" in body
        assert "Manage your booking" not in body

    def test_end_of_itinerary_marker_still_cuts(self):
        from backend.integrations.llm.parser import build_llm_body

        body = build_llm_body(_email(body="SK117 ARN CPH\nBest regards\nSK999 newsletter"))
        assert "SK117" in body and "SK999" not in body


class TestGrounding:
    def test_invented_flight_number_is_dropped(self):
        flights, _ = _run(_answer(flight_number="AD1234"))
        assert flights == []

    def test_airport_written_as_a_city_name_is_kept(self):
        email = _email(body="Voo 4849 Campinas 13:20 Florianópolis 14:35")
        flights, _ = _run(_answer(), email)
        assert [f["arrival_airport"] for f in flights] == ["FLN"]

    def test_leading_zeros_and_spaces_still_match(self):
        from backend.integrations.llm.parser import _flight_number_in_text

        assert _flight_number_in_text({"flight_number": "AY0806"}, "Flight AY 806 to Helsinki")
        assert _flight_number_in_text({"flight_number": "AY806"}, "AY0806 Helsinki")

    def test_an_airline_code_ending_in_a_digit_is_still_found(self):
        """GOL is G3 and Avianca Brasil O6: the mail prints "G31234", "O66175",
        so a digit sits right before the number. These were refused until
        2026-11-25, dropping every such leg the model had read correctly."""
        from backend.integrations.llm.parser import _flight_number_in_text

        assert _flight_number_in_text({"flight_number": "O66175"}, "Número do voo: O66175")
        assert _flight_number_in_text({"flight_number": "G31234"}, "Voo G3 1234 GRU-FLN")
        assert _flight_number_in_text({"flight_number": "G31234"}, "Voo G31234")
        # Still not part of a longer number or another code.
        assert not _flight_number_in_text({"flight_number": "G31234"}, "Pedido XG312345")

    def test_digits_inside_a_longer_number_do_not_count(self):
        from backend.integrations.llm.parser import _flight_number_in_text

        assert not _flight_number_in_text({"flight_number": "AD484"}, "Voo 4849 VCP FLN")

    def test_non_breaking_space_in_the_flight_number_is_kept(self):
        flights, _ = _run(_answer(flight_number="AD 4849"))
        assert [f["flight_number"] for f in flights] == ["AD4849"]

    def test_email_date_in_the_prompt_does_not_ground_a_number(self):
        email = _email(body="Voo 4849 VCP FLN", date=datetime(2026, 1, 5, tzinfo=UTC))
        flights, _ = _run(_answer(flight_number="AD2026"), email)
        assert flights == []


class TestThinking:
    def test_reasoning_is_turned_off(self):
        payload = TestRequest()._payload()
        assert payload["think"] is False


class TestAirportNamedInTheMail:
    """A code is kept when printed, or when a word of its name/city/aliases is."""

    @pytest.fixture
    def airports(self, test_db):
        from backend.database import db_write
        from backend.utils import fold_text

        rows = [
            ("FLN", "Hercílio Luz International Airport", "Florianópolis"),
            ("FLY", "Finley Airport", ""),
            ("BGY", "Il Caravaggio International Airport", "Orio al Serio (BG)"),
            ("ARN", "Stockholm-Arlanda Airport", "Stockholm"),
        ]
        with db_write() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO airports (iata_code, name, city_name, name_folded,"
                " city_folded) VALUES (?, ?, ?, ?, ?)",
                [(c, n, city, fold_text(n), fold_text(city)) for c, n, city in rows],
            )
            conn.execute(
                "INSERT OR IGNORE INTO airport_aliases (alias, iata_code) VALUES ('bergamo', 'BGY')"
            )
        return test_db

    def test_printed_code_is_kept(self, airports):
        from backend.integrations.llm.parser import _airport_in_text

        assert _airport_in_text("ARN", "Departure ARN 06:15")

    def test_city_name_is_kept_accents_folded(self, airports):
        from backend.integrations.llm.parser import _airport_in_text

        assert _airport_in_text("FLN", "Voo de ida 8:00 São Paulo 9:15 Florianópolis")

    def test_alias_is_kept(self, airports):
        from backend.integrations.llm.parser import _airport_in_text

        assert _airport_in_text("BGY", "Milan (Bergamo) 17:55")

    def test_real_airport_the_mail_never_names_is_dropped(self, airports):
        """LATAM's Florianópolis read as FLY, Finley in Australia."""
        from backend.integrations.llm.parser import _airport_in_text

        assert not _airport_in_text("FLY", "Voo de ida 8:00 São Paulo 9:15 Florianópolis")

    def test_unknown_code_is_dropped(self, airports):
        """City codes the model invents (STO for Stockholm) are not airports."""
        from backend.integrations.llm.parser import _airport_in_text

        assert not _airport_in_text("STO", "Stockholm 07:15")

    def test_empty_airports_table_checks_nothing(self, test_db):
        from backend.integrations.llm.parser import _airport_in_text

        assert _airport_in_text("STO", "Stockholm 07:15")

    def test_llm_leg_with_an_unnamed_airport_is_dropped(self, airports):
        email = _email(body="Voo 4849 São Paulo 13:20 Florianópolis 14:35")
        flights, _ = _run(_answer(dep_airport="ARN", arr_airport="FLY"), email)
        assert flights == []


class TestAirportCandidates:
    """The airports a mail names, offered to the model as the only choices."""

    @pytest.fixture
    def airports(self, test_db):
        from backend.database import db_write
        from backend.utils import fold_text

        rows = [
            ("FLN", "Florianópolis"),
            ("GRU", "São Paulo"),
            ("CGH", "São Paulo"),
            ("VCP", "Campinas"),
            ("FLY", "Finley"),
        ]
        with db_write() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO airports (iata_code, name, city_name, city_folded,"
                " scheduled_service) VALUES (?, ?, ?, ?, 1)",
                [(c, c, city, fold_text(city)) for c, city in rows],
            )
            conn.execute(
                "INSERT OR IGNORE INTO airport_aliases (alias, iata_code) VALUES ('viracopos', 'VCP')"
            )
        return test_db

    def test_codes_city_names_and_aliases(self, airports):
        from backend.integrations.llm.parser import airport_candidates

        text = "Voo 4849 VCP 13:20 Florianópolis 14:35, conexão São Paulo, Viracopos"
        assert airport_candidates(text) == ["CGH", "FLN", "GRU", "VCP"]

    def test_unknown_code_is_not_a_candidate(self, airports):
        from backend.integrations.llm.parser import airport_candidates

        assert airport_candidates("Pago com PIX, ref ABC") == []

    def test_arrival_time_is_required_and_never_null(self):
        from backend.integrations.llm.parser import _FLIGHT_SCHEMA

        leg = _FLIGHT_SCHEMA["properties"]["flights"]["items"]
        assert "arr_datetime" in leg["required"]
        assert leg["properties"]["arr_datetime"] == {"type": "string"}


class TestCandidatesAndCheckAgree:
    """The post-answer check accepts exactly the mail's candidate airports."""

    @pytest.fixture
    def airports(self, test_db):
        from backend.database import db_write
        from backend.utils import fold_text

        rows = [
            ("LIN", "Milano Linate Airport", "Segrate (MI)"),
            ("FRA", "Frankfurt am Main Airport", "Frankfurt"),
            ("ARN", "Stockholm-Arlanda Airport", "Stockholm"),
        ]
        with db_write() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO airports (iata_code, name, city_name, name_folded,"
                " city_folded, scheduled_service) VALUES (?, ?, ?, ?, ?, 1)",
                [(c, n, city, fold_text(n), fold_text(city)) for c, n, city in rows],
            )
        return test_db

    def test_airport_named_only_by_a_word_of_its_name_is_a_candidate(self, airports):
        """ "Linate" alone names LIN, though it is neither a city nor an alias."""
        from backend.integrations.llm.parser import _airport_in_text, airport_candidates

        text = "LH 247 Linate 06:10 → Frankfurt 07:40, then Stockholm"
        assert "LIN" in airport_candidates(text)
        assert _airport_in_text("LIN", text)

    def test_check_accepts_exactly_the_candidates(self, airports):
        from backend.integrations.llm.parser import _airport_in_text, airport_candidates

        text = "Frankfurt 07:40 → Stockholm 09:55"
        for code in ("LIN", "FRA", "ARN"):
            assert _airport_in_text(code, text) == (code in airport_candidates(text))


class TestAnswerLength:
    def test_answer_is_capped(self):
        payload = TestRequest()._payload()
        assert payload["options"]["num_predict"] == 2048


class TestDraftForTheReviewPage:
    """llm_draft_flights keeps a leg and clears only the fields the email does
    not support, recording the model's guess; the sync path still drops it."""

    def _draft(self, answer, email):
        from backend.integrations.llm import parser

        with (
            patch("backend.config.settings.OLLAMA_URL", "http://ollama:11434"),
            patch.object(parser, "_call_ollama", return_value=answer),
        ):
            return parser.llm_draft_flights(email)

    def test_an_unsupported_airport_and_time_are_cleared_not_the_leg(self, seeded_airports_db):
        email = _email(
            body="Voo 4849 em 02/03/2026, de Florianópolis FLN às 13:20, destino Milão. Reserva TESTR5"
        )
        answer = _answer(
            flight_number="AD4849",
            dep_airport="FLN",
            arr_airport="MXP",
            dep_datetime="2026-03-02T13:20:00",
            arr_datetime="2026-03-02T18:10:00",
        )
        (leg,) = self._draft(answer, email)
        assert (leg["flight_number"], leg["departure_airport"]) == ("AD4849", "FLN")
        assert leg["departure_datetime"] == "2026-03-02T13:20"
        assert (leg["arrival_airport"], leg["arrival_datetime"]) == ("", "")
        assert leg["doubts"] == {"arrival_airport": "MXP", "arrival_datetime": "2026-03-02T18:10"}

        # The sync path, which nobody reviews, still refuses the whole leg.
        flights, _ = _run(answer, email)
        assert flights == []

    def test_an_unreachable_model_is_an_error_for_the_draft_only(self):
        from backend.integrations.llm import parser

        email = _email(body="Voo 4849 VCP FLN")
        with pytest.raises(parser.LlmUnreachableError):
            self._draft(None, email)
        flights, _ = _run(None, email)
        assert flights == []

    def test_a_printed_time_does_not_vouch_for_the_model_s_date(self, seeded_airports_db):
        email = _email(body="Voo 4849 de VCP às 13:20 para FLN. Reserva TESTR5")
        (leg,) = self._draft(_answer(dep_datetime="2026-03-02T13:20:00"), email)
        assert leg["departure_datetime"] == ""
        assert leg["doubts"]["departure_datetime"] == "2026-03-02T13:20"

    def test_a_date_with_a_month_name_counts(self):
        from backend.integrations.llm.parser import _date_in_text

        assert _date_in_text("2018-11-16T15:40", "FLN 16 NOV 15:40")
        assert _date_in_text("2018-11-16T15:40", "Sexta, 16 de novembro")
        assert _date_in_text("2018-11-16T15:40", "Nov 16, 2018")
        assert _date_in_text("2018-11-16T15:40", "16/11/2018")
        assert not _date_in_text("2018-11-16T15:40", "16 OCT, 11 NOV")

    def test_a_booking_code_not_in_the_email_is_a_doubt(self, seeded_airports_db):
        email = _email(body="Voo 4849 em 02/03/2026 VCP 13:20 FLN. Código PVNQDY")
        answer = _answer(dep_datetime="2026-03-02T13:20:00", booking_reference="ZZZ999")
        (leg,) = self._draft(answer, email)
        # The model's code is in neither the subject nor the body.
        assert leg["booking_reference"] == ""
        assert leg["doubts"]["booking_reference"] == "ZZZ999"

    def test_airport_doubts_follow_a_route_correction(self, seeded_airports_db):
        from backend.integrations.llm import parser

        email = _email(body="Voo 4849 em 02/03/2026 às 13:20, chegada GRU. Reserva TESTR5")
        answer = _answer(dep_airport="FLN", arr_airport="GRU", dep_datetime="2026-03-02T13:20:00")

        def swap(flight):
            flight["departure_airport"], flight["arrival_airport"] = (
                flight["arrival_airport"],
                flight["departure_airport"],
            )
            return flight

        with patch("backend.integrations.routes.check.fix_reversed_route", side_effect=swap):
            (leg,) = self._draft(answer, email)
        # After the swap GRU is the departure and is in the email; FLN, now the
        # arrival, is not — so the arrival is the field cleared.
        assert leg["departure_airport"] == "GRU"
        assert (leg["arrival_airport"], leg["doubts"].get("arrival_airport")) == ("", "FLN")
