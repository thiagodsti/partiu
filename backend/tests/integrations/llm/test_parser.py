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

    def test_schema_limits_both_airports_to_the_candidates(self, airports):
        from backend.integrations.llm.parser import _FLIGHT_SCHEMA, flight_schema

        schema = flight_schema("São Paulo 08:00 → Florianópolis 09:15")
        legs = schema["properties"]["flights"]["items"]["properties"]
        assert legs["dep_airport"]["enum"] == ["CGH", "FLN", "GRU"]
        assert legs["arr_airport"]["enum"] == ["CGH", "FLN", "GRU"]
        # the shared schema is not modified
        assert (
            "enum"
            not in _FLIGHT_SCHEMA["properties"]["flights"]["items"]["properties"]["dep_airport"]
        )

    def test_fewer_than_two_candidates_leaves_airports_free(self, airports):
        from backend.integrations.llm.parser import _FLIGHT_SCHEMA, flight_schema

        assert flight_schema("Your flight to Florianópolis") is _FLIGHT_SCHEMA

    def test_arrival_time_is_required_and_never_null(self):
        from backend.integrations.llm.parser import _FLIGHT_SCHEMA

        leg = _FLIGHT_SCHEMA["properties"]["flights"]["items"]
        assert "arr_datetime" in leg["required"]
        assert leg["properties"]["arr_datetime"] == {"type": "string"}

    def test_llm_request_carries_the_mail_schema(self, airports):
        from unittest.mock import patch

        from backend.integrations.llm import parser

        email = _email(body="Voo 4849 São Paulo 08:00 Florianópolis 09:15")
        with (
            patch("backend.config.settings.OLLAMA_URL", "http://ollama:11434"),
            patch.object(parser, "_call_ollama", return_value=None) as call,
        ):
            parser.llm_extract_flights(email)
        schema = call.call_args.kwargs["schema"]
        legs = schema["properties"]["flights"]["items"]["properties"]
        assert legs["arr_airport"]["enum"] == ["CGH", "FLN", "GRU"]
